from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from bench.adapters.base import Adapter, AdapterError
from bench.adapters.null import null_output
from bench.adapters.oracle import oracle_output
from bench.runner import Runner, main, split_conditions

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _rows(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


class FailingAdapter(Adapter):
    adapter_name = "failing"

    def __init__(self, name=None, config=None, failure_class="api_error", exc=None):
        super().__init__(name, config)
        self.failure_class = failure_class
        self.exc = exc
        self.calls = 0

    def _run(self, case, task, rep, seed):
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        raise AdapterError(self.failure_class, "boom")


class WrongModelAdapter(Adapter):
    adapter_name = "wrongmodel"

    def __init__(self, name=None, config=None):
        super().__init__(name, config)
        self.requested_model = "claude-opus-5"

    def _run(self, case, task, rep, seed):
        return oracle_output(case, task), {"model_served": "claude-opus-4-8", "stop_reason": "end_turn"}, {}


class StopReasonAdapter(Adapter):
    adapter_name = "stopreason"

    def __init__(self, name=None, config=None, stop_reason="max_tokens"):
        super().__init__(name, config)
        self.stop_reason = stop_reason

    def _run(self, case, task, rep, seed):
        return null_output(task), {"model_served": None, "stop_reason": self.stop_reason}, {}


class SlowAdapter(Adapter):
    adapter_name = "slow"

    def _run(self, case, task, rep, seed):
        time.sleep(0.6)
        return oracle_output(case, task), {"model_served": None, "stop_reason": "end_turn"}, {}


def _runner(tmp_path, task="verdict", conditions=("oracle", "null", "mock:p=0.7,g=0.9"), reps=3, **kw):
    kw.setdefault("backoff_base", 0.001)
    kw.setdefault("max_workers", 4)
    return Runner(task=task, conditions=list(conditions), reps=reps, seed=0, data_dir=FIXTURES, out_dir=tmp_path / "run", **kw)


def test_end_to_end_verdict_and_resume(tmp_path):
    runner = _runner(tmp_path)
    summary = runner.run(quiet=True)
    out = tmp_path / "run"
    results = _rows(out / "results.jsonl")
    assert len(results) == 6 * 3 * 3
    assert _rows(out / "errors.jsonl") == []
    assert len(list((out / "trajectories").glob("*.json"))) == 54
    manifest = json.loads((out / "run_manifest.json").read_text())
    assert manifest["task"] == "verdict" and manifest["reps"] == 3 and manifest["seed"] == 0
    assert {c["condition"] for c in manifest["conditions"]} == {"oracle", "null", "mock:p=0.7,g=0.9"}
    assert manifest["data_file_hashes"]["specs/constraints.json"]
    assert "python_version" in manifest and "start_time" in manifest and "git_head" in manifest
    assert (out / "cases_meta.json").exists()
    for row in results:
        assert row["status"] == "ok"
        assert set(row) == {"case_id", "task", "condition", "rep", "status", "grades", "meta", "trajectory_path"}
        assert row["meta"]["attempts"] == 1
        traj = json.loads((out / row["trajectory_path"]).read_text())
        assert traj["input"]["case_id"] == row["case_id"]
        assert "output" in traj and "grader_inputs" in traj and traj["grades"] == row["grades"]
    oracle_rows = [r for r in results if r["condition"] == "oracle"]
    assert all(r["grades"]["overall_correct"] == 1.0 for r in oracle_rows)
    assert summary["conditions"]["oracle"]["mean_overall_correct"] == 1.0
    assert summary["conditions"]["null"]["mean_overall_correct"] < 0.5
    mock_rows = [r for r in results if r["condition"].startswith("mock")]
    assert all(r["meta"]["model_served"] == "mock" for r in mock_rows)

    # resume: nothing re-run, nothing duplicated
    summary2 = _runner(tmp_path).run(quiet=True)
    assert len(_rows(out / "results.jsonl")) == 54
    assert summary2["n_cells"] == 0
    assert summary2["conditions"]["oracle"]["skipped"] == 18


def test_end_to_end_ingestion(tmp_path):
    summary = _runner(tmp_path, task="ingestion", reps=2).run(quiet=True)
    out = tmp_path / "run"
    results = _rows(out / "results.jsonl")
    assert len(results) == 3 * 3 * 2
    assert summary["conditions"]["oracle"]["mean_constraint_f1"] == 1.0
    assert summary["conditions"]["null"]["mean_constraint_f1"] == 0.0
    assert all("distractor_excluded" in r["grades"] for r in results)


def test_failing_adapter_lands_in_errors(tmp_path):
    failing = FailingAdapter(name="failing")
    runner = _runner(tmp_path, conditions=("failing",), reps=1, adapters={"failing": failing}, limit=2)
    runner.run(quiet=True)
    out = tmp_path / "run"
    assert _rows(out / "results.jsonl") == []
    errors = _rows(out / "errors.jsonl")
    assert len(errors) == 2
    assert {e["failure_class"] for e in errors} == {"api_error"}
    assert failing.calls == 6  # three attempts per cell for a transient class
    traj = json.loads(next((out / "trajectories").glob("*.json")).read_text())
    assert traj["error"]["failure_class"] == "api_error"

    # non-transient failures are not retried, and unexpected exceptions become harness_error
    unparseable = FailingAdapter(name="unp", failure_class="unparseable")
    crashing = FailingAdapter(name="crash", exc=RuntimeError("bug"))
    runner = _runner(tmp_path / "b", conditions=("unp", "crash"), reps=1, adapters={"unp": unparseable, "crash": crashing}, limit=1)
    runner.run(quiet=True)
    errors = _rows(tmp_path / "b" / "run" / "errors.jsonl")
    assert {e["condition"]: e["failure_class"] for e in errors} == {"unp": "unparseable", "crash": "harness_error"}
    assert unparseable.calls == 1
    assert "RuntimeError: bug" in next(e for e in errors if e["condition"] == "crash")["detail"]

    # errored cells are skipped on resume unless retry_errors is set
    runner = _runner(tmp_path / "b", conditions=("unp", "crash"), reps=1, adapters={"unp": unparseable, "crash": crashing}, limit=1)
    assert runner.run(quiet=True)["n_cells"] == 0
    runner = _runner(tmp_path / "b", conditions=("unp", "crash"), reps=1, adapters={"unp": unparseable, "crash": crashing}, limit=1, retry_errors=True)
    assert runner.run(quiet=True)["n_cells"] == 2


def test_model_mismatch_lands_in_errors(tmp_path):
    runner = _runner(tmp_path, conditions=("wrong",), reps=1, adapters={"wrong": WrongModelAdapter(name="wrong")}, limit=1)
    runner.run(quiet=True)
    errors = _rows(tmp_path / "run" / "errors.jsonl")
    assert len(errors) == 1 and errors[0]["failure_class"] == "model_mismatch"
    assert "claude-opus-4-8" in errors[0]["detail"]
    assert _rows(tmp_path / "run" / "results.jsonl") == []


def test_truncated_and_refusal_status_still_graded(tmp_path):
    adapters = {"trunc": StopReasonAdapter(name="trunc", stop_reason="max_tokens"), "ref": StopReasonAdapter(name="ref", stop_reason="refusal")}
    runner = _runner(tmp_path, conditions=("trunc", "ref"), reps=1, adapters=adapters, limit=1)
    runner.run(quiet=True)
    rows = _rows(tmp_path / "run" / "results.jsonl")
    assert {r["condition"]: r["status"] for r in rows} == {"trunc": "truncated", "ref": "refusal"}
    assert all("overall_correct" in r["grades"] for r in rows)
    assert _rows(tmp_path / "run" / "errors.jsonl") == []


def test_case_timeout_ceiling(tmp_path):
    runner = _runner(tmp_path, conditions=("slow",), reps=1, adapters={"slow": SlowAdapter(name="slow")}, limit=1, case_timeout=0.2, max_workers=1)
    runner.run(quiet=True)
    errors = _rows(tmp_path / "run" / "errors.jsonl")
    assert len(errors) == 1 and errors[0]["failure_class"] == "timeout"


def test_cli_main_and_condition_splitting(tmp_path, capsys):
    assert split_conditions("oracle,null,mock:p=0.7,g=0.9,H2:k=8") == ["oracle", "null", "mock:p=0.7,g=0.9", "H2:k=8"]
    out = tmp_path / "cli"
    rc = main([
        "--task", "verdict", "--conditions", "oracle,mock:p=0.5,g=1.0", "--reps", "2", "--seed", "1",
        "--data", str(FIXTURES), "--out", str(out), "--case-filter", "GTF-S0", "--limit", "3", "--max-workers", "2",
    ])
    assert rc == 0
    printed = capsys.readouterr().out
    assert "[verdict] oracle:" in printed and "mock:p=0.5,g=1.0" in printed
    rows = _rows(out / "results.jsonl")
    assert len(rows) == 3 * 2 * 2
    assert all(r["case_id"].startswith("GTF-S0") for r in rows)


# ---------------------------------------------------------------------------------------
# report (needs the other agent's bench.stats)
# ---------------------------------------------------------------------------------------

def _stats_ready() -> bool:
    try:
        from bench import report

        return report.stats_available()
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not _stats_ready(), reason="bench.stats not available yet")
def test_report_end_to_end(tmp_path):
    from bench import report

    _runner(tmp_path, conditions=("oracle", "null", "mock:p=0.7,g=0.9"), reps=3).run(quiet=True)
    run_dir = tmp_path / "run"
    rc = report.main(["--run", str(run_dir), "--baseline", "null", "--primary", "overall_correct,constraint_f1,citable_coverage", "--n-boot", "200"])
    assert rc == 0
    text = (run_dir / "report.md").read_text()
    for header in ("## Excluded rows", "## Metrics by condition", "## Paired differences versus baseline `null`",
                   "## pass^k (k = 3) on overall_correct", "## Hard gate: fail on any", "## Paraphrase robustness"):
        assert header in text
    assert "| oracle | overall_correct |" in text
    assert "as_of_prior_version" in text
    # baseline absent from the run is reported, not crashed on
    text2 = report.build_report(run_dir, "H1", ["overall_correct"], n_boot=100)
    assert "not among this run's conditions" in text2


def test_report_fails_clearly_without_stats(monkeypatch, tmp_path):
    from bench import report

    monkeypatch.setattr(report, "_stats", None)
    monkeypatch.setattr(report, "STATS_IMPORT_ERROR", "ModuleNotFoundError: No module named 'bench.stats'")
    with pytest.raises(SystemExit) as exc:
        report.build_report(tmp_path, "H1", ["overall_correct"])
    assert "bench/stats.py" in str(exc.value)
