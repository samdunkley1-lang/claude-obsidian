"""Bench runner.

    python -m bench.runner --task verdict --conditions oracle,null,mock:p=0.7,g=0.9 \
        --reps 5 --seed 0 --data data --out results/<run_id> \
        [--limit N] [--case-filter substring] [--max-workers 4] [--case-timeout 600]

Per (case, condition, rep) cell the runner: skips it when already present in
results.jsonl (or errors.jsonl, unless --retry-errors); calls the adapter under a
wall-clock ceiling with jittered exponential backoff on transient failures (api_error,
timeout) for up to three attempts; asserts model_served == requested_model when the adapter
requests a model; grades the output; writes trajectories/<case>__<condition>__<rep>.json;
appends a ResultRow to results.jsonl or an ErrorRow to errors.jsonl. Rows with status
``truncated`` or ``refusal`` still carry grades (the stats layer excludes them).
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as _dt
import json
import platform
import random
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any

from bench.adapters import build_adapter
from bench.adapters.base import Adapter, AdapterError
from bench.cases import TASKS, build_cases, constraints_for_case, corpus_for_case, data_file_hashes, load_dataset
from bench.graders import grade_ingestion, grade_verdict

MAX_ATTEMPTS = 3
TRANSIENT = ("api_error", "timeout")


class CellTimeout(Exception):
    pass


def _git_head(start: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(start), capture_output=True, text=True, timeout=10
        )
        return out.stdout.strip() if out.returncode == 0 else None
    except Exception:
        return None


def _safe_name(s: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_.=" else "_" for ch in s)


def _call_with_timeout(fn, args: tuple, timeout: float):
    ex = cf.ThreadPoolExecutor(max_workers=1, thread_name_prefix="cell")
    fut = ex.submit(fn, *args)
    try:
        return fut.result(timeout=timeout)
    except cf.TimeoutError as exc:
        raise CellTimeout(f"case exceeded {timeout:.0f}s ceiling") from exc
    finally:
        ex.shutdown(wait=False, cancel_futures=True)


def execute_with_retries(
    adapter: Adapter,
    case: dict,
    task: str,
    rep: int,
    seed: int,
    case_timeout: float,
    max_attempts: int = MAX_ATTEMPTS,
    backoff_base: float = 1.0,
    rng: random.Random | None = None,
) -> tuple[dict, dict, dict, list[dict]]:
    """Run one cell. Returns (output, meta, trajectory, attempt_log) or raises AdapterError."""
    rng = rng or random.Random()
    deadline = time.monotonic() + case_timeout
    attempt_log: list[dict] = []
    for attempt in range(1, max_attempts + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AdapterError("timeout", f"case ceiling {case_timeout:.0f}s exhausted before attempt {attempt}")
        t0 = time.perf_counter()
        try:
            output, meta, trajectory = _call_with_timeout(adapter.run, (case, task, rep, seed), remaining)
        except CellTimeout as exc:
            attempt_log.append({"attempt": attempt, "outcome": "timeout", "detail": str(exc)})
            raise AdapterError("timeout", str(exc)) from exc
        except AdapterError as exc:
            attempt_log.append({"attempt": attempt, "outcome": exc.failure_class, "detail": exc.detail,
                                "latency_ms": (time.perf_counter() - t0) * 1000.0})
            if exc.failure_class in TRANSIENT and attempt < max_attempts:
                delay = backoff_base * (2 ** (attempt - 1)) * (1.0 + rng.random())
                delay = max(0.0, min(delay, deadline - time.monotonic()))
                time.sleep(delay)
                continue
            raise
        attempt_log.append({"attempt": attempt, "outcome": "ok", "latency_ms": (time.perf_counter() - t0) * 1000.0})
        meta["attempts"] = attempt
        return output, meta, trajectory, attempt_log
    raise AdapterError("api_error", "retries exhausted")  # pragma: no cover


def status_from_meta(meta: dict) -> str:
    stop = meta.get("stop_reason")
    if stop == "refusal":
        return "refusal"
    if stop == "max_tokens":
        return "truncated"
    return "ok"


def grade(output: dict, case: dict, task: str) -> dict[str, float | None]:
    corpus = corpus_for_case(case)
    if task == "ingestion":
        return grade_ingestion(output, case, corpus)
    return grade_verdict(output, case, constraints_for_case(case), corpus)


class Runner:
    def __init__(
        self,
        task: str,
        conditions: list[str],
        reps: int,
        seed: int,
        data_dir: str | Path,
        out_dir: str | Path,
        limit: int | None = None,
        case_filter: str | None = None,
        max_workers: int = 4,
        case_timeout: float = 600.0,
        retry_errors: bool = False,
        backoff_base: float = 1.0,
        adapters: dict[str, Adapter] | None = None,
        argv: list[str] | None = None,
        skip_invalid: bool = False,
    ) -> None:
        if task not in TASKS:
            raise ValueError(f"task must be one of {TASKS}")
        self.task = task
        self.condition_specs = list(conditions)
        self.reps = int(reps)
        self.seed = int(seed)
        self.data_dir = Path(data_dir)
        self.out_dir = Path(out_dir)
        self.limit = limit
        self.case_filter = case_filter
        self.max_workers = max(1, int(max_workers))
        self.case_timeout = float(case_timeout)
        self.retry_errors = retry_errors
        self.backoff_base = float(backoff_base)
        self.skip_invalid = skip_invalid
        self.argv = argv or []
        self.adapters: dict[str, Adapter] = adapters or {spec: build_adapter(spec) for spec in self.condition_specs}
        self._lock = threading.Lock()
        self.results_path = self.out_dir / "results.jsonl"
        self.errors_path = self.out_dir / "errors.jsonl"
        self.traj_dir = self.out_dir / "trajectories"

    # ---- setup ---------------------------------------------------------------------
    def load_cases(self) -> list[dict]:
        ds = load_dataset(self.data_dir, skip_invalid=self.skip_invalid)
        cases = build_cases(ds, self.task)
        if self.case_filter:
            cases = [c for c in cases if self.case_filter in c["case_id"]]
        if self.limit is not None:
            cases = cases[: self.limit]
        return cases

    def write_manifest(self, cases: list[dict]) -> dict:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.traj_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "run_id": self.out_dir.name,
            "task": self.task,
            "conditions": [a.describe() for a in self.adapters.values()],
            "reps": self.reps,
            "seed": self.seed,
            "data_dir": str(self.data_dir),
            "data_file_hashes": data_file_hashes(self.data_dir),
            "git_head": _git_head(Path(__file__).resolve().parent),
            "start_time": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "python_version": sys.version,
            "platform": platform.platform(),
            "argv": self.argv,
            "limit": self.limit,
            "case_filter": self.case_filter,
            "max_workers": self.max_workers,
            "case_timeout": self.case_timeout,
            "n_cases": len(cases),
            "case_ids": [c["case_id"] for c in cases],
        }
        (self.out_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        meta = {}
        for c in cases:
            entry = {"task": self.task, "variant_kind": c.get("variant_kind"), "variant_of": c.get("variant_of"),
                     "fund": c.get("fund"), "tags": c.get("tags", [])}
            if self.task == "verdict":
                entry["gold_overall"] = c["gold"].get("overall")
                entry["decision_type"] = c.get("decision_type")
            else:
                entry["doc_id"] = c.get("doc_id")
                entry["version"] = c.get("version")
            meta[c["case_id"]] = entry
        (self.out_dir / "cases_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return manifest

    def existing_keys(self) -> set[tuple[str, str, int]]:
        keys: set[tuple[str, str, int]] = set()
        paths = [self.results_path] if self.retry_errors else [self.results_path, self.errors_path]
        for path in paths:
            if not path.exists():
                continue
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    keys.add((row["case_id"], row["condition"], int(row["rep"])))
        return keys

    # ---- one cell ------------------------------------------------------------------
    def _trajectory_path(self, case_id: str, condition: str, rep: int) -> Path:
        return self.traj_dir / f"{_safe_name(case_id)}__{_safe_name(condition)}__{rep}.json"

    def run_cell(self, case: dict, condition: str, rep: int) -> tuple[str, dict]:
        adapter = self.adapters[condition]
        case_id = case["case_id"]
        traj_path = self._trajectory_path(case_id, condition, rep)
        record: dict[str, Any] = {
            "case_id": case_id, "task": self.task, "condition": condition, "rep": rep, "seed": self.seed,
            "adapter": adapter.describe(), "input": case,
        }
        rng = random.Random(f"{case_id}|{condition}|{rep}|{self.seed}")
        try:
            output, meta, trajectory, attempt_log = execute_with_retries(
                adapter, case, self.task, rep, self.seed, self.case_timeout,
                backoff_base=self.backoff_base, rng=rng,
            )
        except AdapterError as exc:
            record["error"] = {"failure_class": exc.failure_class, "detail": exc.detail}
            self._write_json(traj_path, record)
            return "error", self._error_row(case_id, condition, rep, exc.failure_class, exc.detail)
        except Exception as exc:  # noqa: BLE001 - anything else is a harness bug
            detail = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[-2000:]}"
            record["error"] = {"failure_class": "harness_error", "detail": detail}
            self._write_json(traj_path, record)
            return "error", self._error_row(case_id, condition, rep, "harness_error", detail)

        record["output"] = output
        record["meta"] = meta
        record["adapter_trajectory"] = trajectory
        record["attempts"] = attempt_log
        record["grader_inputs"] = {
            "corpus_text_by_rendering": corpus_for_case(case),
            "constraints_by_id": constraints_for_case(case),
            "gold": case.get("gold"),
        }

        requested = adapter.requested_model
        served = meta.get("model_served")
        if requested and served != requested:
            detail = f"requested {requested!r} but served {served!r}"
            record["error"] = {"failure_class": "model_mismatch", "detail": detail}
            self._write_json(traj_path, record)
            return "error", self._error_row(case_id, condition, rep, "model_mismatch", detail)

        try:
            grades = grade(output, case, self.task)
        except Exception as exc:  # noqa: BLE001
            detail = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[-2000:]}"
            record["error"] = {"failure_class": "grader_error", "detail": detail}
            self._write_json(traj_path, record)
            return "error", self._error_row(case_id, condition, rep, "grader_error", detail)

        status = status_from_meta(meta)
        record["grades"] = grades
        record["status"] = status
        self._write_json(traj_path, record)
        row = {
            "case_id": case_id,
            "task": self.task,
            "condition": condition,
            "rep": rep,
            "status": status,
            "grades": grades,
            "meta": meta,
            "trajectory_path": str(traj_path.relative_to(self.out_dir)),
        }
        return "result", row

    def _error_row(self, case_id: str, condition: str, rep: int, failure_class: str, detail: str) -> dict:
        return {"case_id": case_id, "task": self.task, "condition": condition, "rep": rep,
                "failure_class": failure_class, "detail": detail[:4000]}

    def _write_json(self, path: Path, obj: Any) -> None:
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(obj, indent=1, default=str), encoding="utf-8")
        tmp.replace(path)

    def _append(self, path: Path, row: dict) -> None:
        with self._lock:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, default=str) + "\n")

    # ---- all cells -----------------------------------------------------------------
    def run(self, quiet: bool = False) -> dict:
        cases = self.load_cases()
        self.write_manifest(cases)
        self.results_path.touch()
        self.errors_path.touch()
        done = self.existing_keys()
        cells = [
            (case, cond, rep)
            for case in cases
            for cond in self.condition_specs
            for rep in range(self.reps)
            if (case["case_id"], cond, rep) not in done
        ]
        counts: dict[str, dict[str, int]] = {c: {"ok": 0, "truncated": 0, "refusal": 0, "error": 0, "skipped": 0} for c in self.condition_specs}
        for key in done:
            if key[1] in counts:
                counts[key[1]]["skipped"] += 1
        metric_sums: dict[str, list[float]] = {c: [] for c in self.condition_specs}
        primary = "overall_correct" if self.task == "verdict" else "constraint_f1"

        def _handle(kind: str, row: dict) -> None:
            cond = row["condition"]
            if kind == "result":
                self._append(self.results_path, row)
                counts[cond][row["status"]] += 1
                v = row["grades"].get(primary)
                if row["status"] == "ok" and v is not None:
                    metric_sums[cond].append(float(v))
            else:
                self._append(self.errors_path, row)
                counts[cond]["error"] += 1

        if self.max_workers == 1 or len(cells) <= 1:
            for case, cond, rep in cells:
                _handle(*self.run_cell(case, cond, rep))
        else:
            with cf.ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="bench") as ex:
                futures = [ex.submit(self.run_cell, case, cond, rep) for case, cond, rep in cells]
                for fut in cf.as_completed(futures):
                    _handle(*fut.result())

        summary = {"task": self.task, "n_cases": len(cases), "n_cells": len(cells), "conditions": {}}
        for cond in self.condition_specs:
            vals = metric_sums[cond]
            mean = (sum(vals) / len(vals)) if vals else None
            summary["conditions"][cond] = {**counts[cond], f"mean_{primary}": mean}
            if not quiet:
                mean_s = f"{mean:.3f}" if mean is not None else "n/a"
                c = counts[cond]
                print(
                    f"[{self.task}] {cond}: ok={c['ok']} truncated={c['truncated']} refusal={c['refusal']} "
                    f"errors={c['error']} skipped={c['skipped']} mean_{primary}={mean_s}"
                )
        (self.out_dir / "run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return summary


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m bench.runner", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--task", required=True, choices=TASKS)
    p.add_argument("--conditions", required=True, help="comma-separated condition specs, e.g. oracle,null,mock:p=0.7,g=0.9")
    p.add_argument("--reps", type=int, default=1)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--data", default="data")
    p.add_argument("--out", default=None, help="results/<run_id>; default results/<task>-<timestamp>")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--case-filter", default=None)
    p.add_argument("--max-workers", type=int, default=4)
    p.add_argument("--case-timeout", type=float, default=600.0)
    p.add_argument("--retry-errors", action="store_true", help="re-run cells present in errors.jsonl")
    p.add_argument("--backoff-base", type=float, default=1.0, help="seconds; base of the retry backoff")
    p.add_argument("--skip-invalid", action="store_true", help="drop scenarios/renderings with dangling references instead of failing")
    return p


def split_conditions(spec: str) -> list[str]:
    """Split on commas that separate conditions, not the commas inside key=value configs.

    A comma starts a new condition when the following token does not contain '='."""
    out: list[str] = []
    for tok in spec.split(","):
        tok = tok.strip()
        if not tok:
            continue
        if out and "=" in tok and ":" not in tok:
            out[-1] = out[-1] + "," + tok
        else:
            out.append(tok)
    return out


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    conditions = split_conditions(args.conditions)
    out = args.out or str(Path("results") / f"{args.task}-{_dt.datetime.now().strftime('%Y%m%d-%H%M%S')}")
    runner = Runner(
        task=args.task, conditions=conditions, reps=args.reps, seed=args.seed, data_dir=args.data, out_dir=out,
        limit=args.limit, case_filter=args.case_filter, max_workers=args.max_workers, case_timeout=args.case_timeout,
        retry_errors=args.retry_errors, backoff_base=args.backoff_base, argv=list(argv or sys.argv[1:]),
        skip_invalid=args.skip_invalid,
    )
    runner.run()
    print(f"run written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
