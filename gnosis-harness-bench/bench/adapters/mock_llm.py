"""Deterministic pseudo-model for tests and statistical validation.

Config: ``{"p_correct": float, "p_ground": float}`` (defaults 1.0). The RNG is seeded by
sha256(case_id, condition, rep, seed) so a given cell is reproducible and independent of
thread scheduling. With probability ``p_correct`` the oracle output is returned; otherwise
a plausible wrong output (adjacent severity, one rule hit dropped, wrong verb, perturbed
threshold). Each citation stays grounded with probability ``p_ground`` and is otherwise
replaced by a fabricated quote. Reports ``model_served == requested_model == "mock"``.
"""
from __future__ import annotations

import copy
import hashlib
import random

from bench.adapters.base import Adapter
from bench.adapters.oracle import oracle_output
from bench.graders import severity_rank

_SEVERITIES = ["pass", "warn", "breach", "hard_block"]
_VERBS = ["approve", "hold", "escalate", "request-exception", "reject", "gather-more-data"]
_FABRICATED = "The Fund shall not exceed 999% of net asset value in any circumstance."


def cell_seed(case_id: str, condition: str, rep: int, seed: int) -> int:
    digest = hashlib.sha256(f"{case_id}|{condition}|{rep}|{seed}".encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def _perturb_verdict(out: dict, rng: random.Random) -> dict:
    out = copy.deepcopy(out)
    rank = severity_rank.get(out["overall"], 0)
    candidates = [r for r in (rank - 1, rank + 1) if 0 <= r <= 3]
    out["overall"] = _SEVERITIES[rng.choice(candidates)]
    if out["rules_hit"]:
        out["rules_hit"].pop(rng.randrange(len(out["rules_hit"])))
    wrong_verbs = [v for v in _VERBS if v != out["recommendation_verb"]]
    out["recommendation_verb"] = rng.choice(wrong_verbs)
    if out["overall"] == "hard_block":
        out["approval_path"] = []
    elif out["overall"] == "pass":
        out["approval_path"] = ["PM"]
    elif out["overall"] == "warn":
        out["approval_path"] = ["PM", "CIO"]
    else:
        out["approval_path"] = ["PM", "CIO", "Compliance"]
    return out


def _perturb_ingestion(out: dict, rng: random.Random) -> dict:
    out = copy.deepcopy(out)
    cons = out["constraints"]
    if cons:
        cons.pop(rng.randrange(len(cons)))
    if cons:
        victim = rng.choice(cons)
        thr = victim.get("threshold")
        if isinstance(thr, (int, float)) and not isinstance(thr, bool):
            victim["threshold"] = thr * 2 + 1
        elif isinstance(thr, list):
            victim["threshold"] = [v * 2 + 1 if isinstance(v, (int, float)) else v for v in thr]
        else:
            victim["comparator"] = "prohibited" if victim.get("comparator") != "prohibited" else "<="
    return out


def _degrade_citations(out: dict, task: str, p_ground: float, rng: random.Random) -> dict:
    if task == "verdict":
        for c in out.get("citations", []):
            if rng.random() >= p_ground:
                c["quote"] = _FABRICATED
    else:
        for c in out.get("constraints", []):
            if rng.random() >= p_ground:
                c["evidence"]["quote"] = _FABRICATED
    return out


class MockLLMAdapter(Adapter):
    adapter_name = "mock"

    def __init__(self, name: str | None = None, config: dict | None = None) -> None:
        cfg = {"p_correct": 1.0, "p_ground": 1.0}
        cfg.update(config or {})
        super().__init__(name, cfg)
        self.p_correct = float(self.config["p_correct"])
        self.p_ground = float(self.config["p_ground"])
        self.requested_model = "mock"

    def _run(self, case: dict, task: str, rep: int, seed: int) -> tuple[dict, dict, dict]:
        rng = random.Random(cell_seed(case["case_id"], self.name, rep, seed))
        out = oracle_output(case, task)
        correct = rng.random() < self.p_correct
        if not correct:
            out = _perturb_verdict(out, rng) if task == "verdict" else _perturb_ingestion(out, rng)
        out = _degrade_citations(out, task, self.p_ground, rng)
        meta = {
            "model_served": "mock",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
        }
        return out, meta, {"source": "mock", "correct_draw": correct, "cell_seed": cell_seed(case["case_id"], self.name, rep, seed)}
