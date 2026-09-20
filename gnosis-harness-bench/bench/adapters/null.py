"""Null adapter: a constant answer, the floor every discriminating metric must clear."""
from __future__ import annotations

from bench.adapters.base import Adapter


def null_output(task: str) -> dict:
    if task == "ingestion":
        return {"constraints": []}
    if task == "verdict":
        return {
            "rules_hit": [],
            "overall": "pass",
            "approval_path": ["PM"],
            "recommendation_verb": "approve",
            "rationale": "No issues found.",
            "citations": [],
        }
    raise ValueError(f"unknown task {task!r}")


class NullAdapter(Adapter):
    adapter_name = "null"

    def _run(self, case: dict, task: str, rep: int, seed: int) -> tuple[dict, dict, dict]:
        return null_output(task), {"model_served": None, "stop_reason": "end_turn"}, {"source": "constant"}
