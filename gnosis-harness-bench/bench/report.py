"""Report generation.

    python -m bench.report --run results/<run_id> --baseline H1 \
        --primary overall_correct,constraint_f1,citable_coverage

Reads results.jsonl, errors.jsonl, cases_meta.json and the trajectories of one run and
writes report.md next to them. Statistics come from bench.stats (owned by another agent):
summarize, to_markdown_table, paired_diff, pass_k, holm_bonferroni. If bench.stats is not
importable the CLI exits with a clear message.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from bench.graders import INGESTION_METRICS, VERDICT_METRICS, severity_rank

STATS_IMPORT_ERROR: str | None = None
try:  # pragma: no cover - depends on the other agent's module being present
    from bench import stats as _stats
except Exception as exc:  # noqa: BLE001
    _stats = None
    STATS_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"

REQUIRED_STATS = ("summarize", "to_markdown_table", "paired_diff", "pass_k", "holm_bonferroni")


def stats_available() -> bool:
    return _stats is not None and all(hasattr(_stats, fn) for fn in REQUIRED_STATS)


def require_stats() -> Any:
    if _stats is None:
        raise SystemExit(
            "bench.report needs bench/stats.py (summarize, to_markdown_table, paired_diff, pass_k, "
            f"holm_bonferroni) but it could not be imported: {STATS_IMPORT_ERROR}"
        )
    missing = [fn for fn in REQUIRED_STATS if not hasattr(_stats, fn)]
    if missing:
        raise SystemExit(f"bench.stats is present but lacks {missing}; the report cannot be produced")
    return _stats


# ---------------------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------------------

def read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    if not path.exists():
        return rows
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_run(run_dir: str | Path) -> dict[str, Any]:
    run = Path(run_dir)
    manifest = json.loads((run / "run_manifest.json").read_text(encoding="utf-8")) if (run / "run_manifest.json").exists() else {}
    cases_meta = json.loads((run / "cases_meta.json").read_text(encoding="utf-8")) if (run / "cases_meta.json").exists() else {}
    return {
        "dir": run,
        "manifest": manifest,
        "cases_meta": cases_meta,
        "results": read_jsonl(run / "results.jsonl"),
        "errors": read_jsonl(run / "errors.jsonl"),
    }


def _is_num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and not math.isnan(float(x))


def _fmt(x: Any, digits: int = 3) -> str:
    if x is None:
        return "n/a"
    if isinstance(x, bool):
        return str(x)
    if isinstance(x, (int, float)):
        return f"{x:.{digits}f}" if _is_num(x) else "n/a"
    return str(x)


def _md_table(header: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    for r in rows:
        lines.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------
# report pieces that need no stats module
# ---------------------------------------------------------------------------------------

def excluded_counts(results: list[dict], errors: list[dict], conditions: list[str]) -> str:
    rows = []
    for cond in conditions:
        res = [r for r in results if r["condition"] == cond]
        errs = [e for e in errors if e["condition"] == cond]
        by_status = Counter(r["status"] for r in res)
        by_class = Counter(e["failure_class"] for e in errs)
        err_s = ", ".join(f"{k}={v}" for k, v in sorted(by_class.items())) or "none"
        rows.append([cond, by_status.get("ok", 0), by_status.get("truncated", 0), by_status.get("refusal", 0), len(errs), err_s])
    return _md_table(["condition", "ok", "truncated (excluded)", "refusal (excluded)", "errors (excluded)", "error classes"], rows)


def hard_gate_fail_on_any(results: list[dict], conditions: list[str]) -> str:
    """Share of hard_block-gold cases where every rep was correct (hard_block_correct == 1)."""
    rows = []
    for cond in conditions:
        per_case: dict[str, list[float]] = defaultdict(list)
        for r in results:
            if r["condition"] != cond or r["status"] != "ok":
                continue
            v = r["grades"].get("hard_block_correct")
            if v is not None:
                per_case[r["case_id"]].append(float(v))
        if not per_case:
            rows.append([cond, 0, "n/a"])
            continue
        all_ok = sum(1 for vals in per_case.values() if all(v >= 1.0 for v in vals))
        rows.append([cond, len(per_case), _fmt(all_ok / len(per_case))])
    return _md_table(["condition", "hard_block cases", "share with every rep correct"], rows)


def _model_overall(run_dir: Path, row: dict) -> str | None:
    path = run_dir / row.get("trajectory_path", "")
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    out = rec.get("output") or {}
    v = out.get("overall")
    return str(v).strip().casefold() if isinstance(v, str) else None


def _majority(values: list[str]) -> str | None:
    if not values:
        return None
    counts = Counter(values)
    top = max(counts.values())
    winners = sorted(v for v, c in counts.items() if c == top)
    # break ties by severity so the choice is deterministic
    return max(winners, key=lambda v: severity_rank.get(v, -1))


def paraphrase_robustness(run: dict, conditions: list[str]) -> str:
    """Group scenarios by variant_of. For each group and condition, take the majority-over-reps
    overall verdict of every member. A group is robust when, for every variant, the relation
    between the variant's verdict and the canonical's verdict matches the relation between
    their gold verdicts (equal when the gold is equal, which is the paraphrase case; different
    when the gold differs, as for as_of_prior_version). Reported per variant_kind."""
    meta = run["cases_meta"]
    if not meta or any(m.get("task") != "verdict" for m in meta.values()):
        return "_Not a verdict run; paraphrase robustness does not apply._"
    groups: dict[str, list[str]] = defaultdict(list)
    for cid, m in meta.items():
        if m.get("variant_of"):
            groups[m["variant_of"]].append(cid)
    if not groups:
        return "_No variant groups (no scenario has variant_of set)._"
    verdicts: dict[tuple[str, str], list[str]] = defaultdict(list)
    for r in run["results"]:
        if r["status"] != "ok":
            continue
        v = _model_overall(run["dir"], r)
        if v:
            verdicts[(r["condition"], r["case_id"])].append(v)
    kinds = sorted({meta[c].get("variant_kind", "?") for cs in groups.values() for c in cs})
    rows = []
    for cond in conditions:
        per_kind_ok: dict[str, list[float]] = defaultdict(list)
        for canon, variants in groups.items():
            if canon not in meta:
                continue
            mc = _majority(verdicts.get((cond, canon), []))
            if mc is None:
                continue
            gold_c = str(meta[canon].get("gold_overall", "")).casefold()
            for var in variants:
                mv = _majority(verdicts.get((cond, var), []))
                if mv is None:
                    continue
                gold_v = str(meta[var].get("gold_overall", "")).casefold()
                expected_same = gold_v == gold_c
                ok = (mv == mc) == expected_same
                per_kind_ok[meta[var].get("variant_kind", "?")].append(1.0 if ok else 0.0)
        row = [cond]
        for kind in kinds:
            vals = per_kind_ok.get(kind, [])
            row.append(f"{_fmt(sum(vals) / len(vals))} (n={len(vals)})" if vals else "n/a")
        rows.append(row)
    return _md_table(["condition"] + kinds, rows)


# ---------------------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------------------

def _get(d: Any, key: str, default: Any = None) -> Any:
    if isinstance(d, dict):
        return d.get(key, default)
    return getattr(d, key, default)


def build_report(run_dir: str | Path, baseline: str, primary: list[str], n_boot: int = 10000, seed: int = 0) -> str:
    st = require_stats()
    run = load_run(run_dir)
    results, errors, manifest = run["results"], run["errors"], run["manifest"]
    task = manifest.get("task") or (results[0]["task"] if results else "verdict")
    conditions = [c["condition"] for c in manifest.get("conditions", [])] or sorted({r["condition"] for r in results})
    reps = int(manifest.get("reps") or max((r["rep"] for r in results), default=0) + 1)
    all_metrics = list(VERDICT_METRICS if task == "verdict" else INGESTION_METRICS)
    primary = [m for m in primary if m in all_metrics] or [all_metrics[0]]
    ok_rows = [r for r in results if r["status"] == "ok"]

    lines: list[str] = []
    lines.append(f"# Bench report: {manifest.get('run_id', Path(run_dir).name)}")
    lines.append("")
    lines.append(f"Task: **{task}**. Conditions: {', '.join(conditions)}. Reps: {reps}. Seed: {manifest.get('seed')}. "
                 f"Cases: {manifest.get('n_cases', 'n/a')}. Git HEAD: `{manifest.get('git_head')}`. Started: {manifest.get('start_time')}.")
    lines.append("")
    lines.append("## Excluded rows")
    lines.append("")
    lines.append("Rows with status `truncated` or `refusal` carry grades but are excluded from every statistic below; error rows have no grades.")
    lines.append("")
    lines.append(excluded_counts(results, errors, conditions))
    lines.append("")

    lines.append("## Metrics by condition")
    lines.append("")
    lines.append("Mean over `ok` rows, all reps pooled. `n/a` means the metric did not apply to any row.")
    lines.append("")
    try:
        summary = st.summarize(ok_rows, all_metrics, conditions, task=task)
        lines.append(st.to_markdown_table(summary, all_metrics, conditions, digits=3))
    except Exception as exc:  # noqa: BLE001
        lines.append(f"_summarize failed: {type(exc).__name__}: {exc}_")
    lines.append("")

    lines.append(f"## Paired differences versus baseline `{baseline}`")
    lines.append("")
    if baseline not in conditions:
        lines.append(f"_Baseline `{baseline}` is not among this run's conditions; paired differences skipped._")
    else:
        cells: list[tuple[str, str, dict]] = []
        for cond in conditions:
            if cond == baseline:
                continue
            for metric in primary:
                try:
                    d = st.paired_diff(ok_rows, cond, baseline, metric, task=task, n_boot=n_boot, seed=seed)
                except Exception as exc:  # noqa: BLE001
                    d = {"error": f"{type(exc).__name__}: {exc}"}
                cells.append((cond, metric, d))
        pvals = [_get(d, "p_boot") for _, _, d in cells]
        valid_idx = [i for i, p in enumerate(pvals) if _is_num(p) and 0.0 <= float(p) <= 1.0]
        adjusted: dict[int, float] = {}
        if valid_idx:
            try:
                adj = st.holm_bonferroni([pvals[i] for i in valid_idx])
                adjusted = {i: float(a) for i, a in zip(valid_idx, adj)}
            except Exception:  # noqa: BLE001
                adjusted = {}
        rows = []
        for i, (cond, metric, d) in enumerate(cells):
            if "error" in d:
                rows.append([cond, metric, d["error"], "", "", "", "", "", ""])
                continue
            mc = _get(d, "mcnemar")
            mc_s = _fmt(_get(mc, "p")) if isinstance(mc, dict) else _fmt(mc)
            rows.append([
                cond, metric, _fmt(_get(d, "diff")), _fmt(_get(d, "ci_lo")), _fmt(_get(d, "ci_hi")),
                _fmt(_get(d, "p_boot")), _fmt(adjusted.get(i)), str(_get(d, "n_cases", "")), mc_s,
            ])
        lines.append("Difference is condition minus baseline on per-case means; CI and p from paired bootstrap; p_holm is Holm-adjusted across every (condition, metric) pair in this table.")
        lines.append("")
        lines.append(_md_table(["condition", "metric", "diff", "ci_lo", "ci_hi", "p_boot", "p_holm", "n_cases", "mcnemar p"], rows))
    lines.append("")

    lines.append(f"## pass^k (k = {reps}) on overall_correct")
    lines.append("")
    if any("overall_correct" in r["grades"] for r in ok_rows):
        rows = []
        for cond in conditions:
            try:
                pk = st.pass_k(ok_rows, cond, "overall_correct", reps, task=task, n_boot=n_boot, seed=seed)
                rows.append([cond, _fmt(_get(pk, "estimate")), _fmt(_get(pk, "ci_lo")), _fmt(_get(pk, "ci_hi"))])
            except Exception as exc:  # noqa: BLE001
                rows.append([cond, f"error: {type(exc).__name__}: {exc}", "", ""])
        lines.append(_md_table(["condition", "pass^k", "ci_lo", "ci_hi"], rows))
    else:
        lines.append("_overall_correct is not graded for this task._")
    lines.append("")

    lines.append("## Hard gate: fail on any")
    lines.append("")
    lines.append(hard_gate_fail_on_any(results, conditions))
    lines.append("")

    lines.append("## Paraphrase robustness")
    lines.append("")
    lines.append("Groups are scenarios sharing a `variant_of`. Verdicts are the majority over reps. A group counts as robust when each variant's verdict agrees with the canonical's exactly when their gold verdicts agree (paraphrase-type variants must match; as_of_prior_version and other gold-changing variants must differ).")
    lines.append("")
    lines.append(paraphrase_robustness(run, conditions))
    lines.append("")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m bench.report", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run", required=True, help="results/<run_id>")
    p.add_argument("--baseline", default="H1")
    p.add_argument("--primary", default="overall_correct,constraint_f1,citable_coverage")
    p.add_argument("--n-boot", type=int, default=10000)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", default=None, help="defaults to <run>/report.md")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    primary = [m.strip() for m in args.primary.split(",") if m.strip()]
    text = build_report(args.run, args.baseline, primary, n_boot=args.n_boot, seed=args.seed)
    out = Path(args.out) if args.out else Path(args.run) / "report.md"
    out.write_text(text, encoding="utf-8")
    print(f"report written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
