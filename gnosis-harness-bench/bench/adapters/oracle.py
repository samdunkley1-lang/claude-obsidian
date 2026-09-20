"""Oracle adapter: converts the gold into the output shape.

It scores 1.0 on every applicable metric by construction and doubles as the reference
"ideal output" the mock model degrades from. Quotes are taken from the rendering text:
the canonical_text when it appears verbatim, otherwise the sentence of the rendering that
best overlaps the canonical_text and contains the limit token, so citations stay grounded
even on paraphrased renderings.
"""
from __future__ import annotations

import re

from bench.adapters.base import Adapter
from bench.graders import contains_threshold_token, is_grounded, normalize_text

_SENTENCE_SPLIT = re.compile(r"(?<=[.;:])\s+|\n+")


def find_quote(text: str, constraint: dict) -> str:
    """Best verbatim span of ``text`` supporting ``constraint``."""
    canonical = constraint.get("canonical_text") or ""
    if canonical and is_grounded(canonical, text):
        return canonical
    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]
    canon_tokens = set(normalize_text(canonical).split())
    best, best_score = None, -1.0
    for s in sentences:
        if not contains_threshold_token(s, constraint):
            continue
        toks = set(normalize_text(s).split())
        score = len(toks & canon_tokens) / (len(canon_tokens) or 1)
        if score > best_score:
            best, best_score = s, score
    if best is not None:
        return best
    return canonical


def oracle_ingestion(case: dict) -> dict:
    text = case["text"]
    constraints = []
    for c in case["gold"]:
        constraints.append(
            {
                "type": c["type"],
                "scope": dict(c["scope"]),
                "comparator": c["comparator"],
                "threshold": c["threshold"],
                "unit": c["unit"],
                "effective_from": c["effective_from"],
                "evidence": {
                    "rendering_id": case["rendering_id"],
                    "quote": find_quote(text, c),
                    "claims_constraint": c["id"],
                },
            }
        )
    return {"constraints": constraints}


def _rendering_for(case: dict, constraint: dict) -> dict | None:
    """The supplied rendering of the version in force for the constraint's document."""
    gold = case["gold"]
    doc_id = constraint["doc_id"]
    in_force = gold.get("version_in_force", {}).get(doc_id)
    docs = [d for d in case["documents"] if d["doc_id"] == doc_id]
    if not docs:
        return None
    for d in docs:
        if in_force is not None and d["version"] == in_force and constraint["id"] in d["constraint_ids"]:
            return d
    for d in docs:
        if constraint["id"] in d["constraint_ids"]:
            return d
    return docs[0]


def oracle_verdict(case: dict) -> dict:
    gold = case["gold"]
    constraints = case["constraints"]
    rules_hit = []
    for cid in gold["rules_hit"]:
        c = constraints[cid]
        rules_hit.append(
            {
                "type": c["type"],
                "scope": dict(c["scope"]),
                "verdict": gold["verdicts"].get(cid, "warn"),
                "limit": c["threshold"],
                "exposure_post_trade": None,
            }
        )
    citations = []
    for cid in gold["citable_constraint_ids"]:
        c = constraints[cid]
        d = _rendering_for(case, c)
        if d is None:
            continue
        citations.append(
            {
                "rendering_id": d["rendering_id"],
                "quote": find_quote(d["text"], c),
                "claims_constraint": cid,
            }
        )
    parts = []
    for cid in gold["rules_hit"]:
        c = constraints[cid]
        parts.append(f"Rule {cid} ({c['type']}) is {gold['verdicts'].get(cid, 'warn')} against the stated limit.")
    if not parts:
        parts.append("Every rule in scope passes post-trade.")
    path = ", ".join(gold["approval_path"]) if gold["approval_path"] else "none (no path exists)"
    parts.append(f"Overall verdict {gold['overall']}; approval path {path}; recommendation {gold['recommendation_verb']}.")
    return {
        "rules_hit": rules_hit,
        "overall": gold["overall"],
        "approval_path": list(gold["approval_path"]),
        "recommendation_verb": gold["recommendation_verb"],
        "rationale": " ".join(parts),
        "citations": citations,
    }


def oracle_output(case: dict, task: str) -> dict:
    if task == "ingestion":
        return oracle_ingestion(case)
    if task == "verdict":
        return oracle_verdict(case)
    raise ValueError(f"unknown task {task!r}")


class OracleAdapter(Adapter):
    adapter_name = "oracle"

    def _run(self, case: dict, task: str, rep: int, seed: int) -> tuple[dict, dict, dict]:
        output = oracle_output(case, task)
        return output, {"model_served": None, "stop_reason": "end_turn"}, {"source": "gold"}
