"""Emit the rendering plan: which prose renderings each document needs and what each must contain.

Run: python -m bench.render_plan --specs data/specs --out data/specs/rendering_plan.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

STYLES = ["legal", "bullets", "narrative", "tabular", "memo"]


def build_plan(constraints: list[dict], documents: list[dict]) -> list[dict]:
    by_id = {c["id"]: c for c in constraints}
    plan: list[dict] = []
    style_i = 0
    for doc in documents:
        fund, dt = doc["fund"], doc["doc_type"]
        latest = max(v["version"] for v in doc["versions"])
        for v in doc["versions"]:
            style = STYLES[style_i % len(STYLES)]; style_i += 1
            plan.append({
                "rendering_id": f"{doc['doc_id']}-v{v['version']}-canonical", "doc_id": doc["doc_id"], "fund": fund,
                "version": v["version"], "variant_kind": "canonical", "style": style,
                "path": f"{fund}/{doc['doc_id']}-v{v['version']}-canonical.md",
                "include_constraint_ids": v["constraint_ids"],
                "instructions": "Render every listed constraint (binding ones as binding rules, distractors as non-binding statements).",
            })
        vlat = next(v for v in doc["versions"] if v["version"] == latest)
        if dt in ("guidelines", "ips", "esg_policy"):
            plan.append({
                "rendering_id": f"{doc['doc_id']}-v{latest}-paraphrase", "doc_id": doc["doc_id"], "fund": fund,
                "version": latest, "variant_kind": "paraphrase", "style": STYLES[(style_i + 2) % 5],
                "path": f"{fund}/{doc['doc_id']}-v{latest}-paraphrase.md",
                "include_constraint_ids": vlat["constraint_ids"],
                "instructions": "Same rules, entirely different wording and document structure from the canonical rendering. Every threshold, scope and unit must be identical.",
            })
        if dt == "guidelines":
            plan.append({
                "rendering_id": f"{doc['doc_id']}-v{latest}-adv_negation", "doc_id": doc["doc_id"], "fund": fund,
                "version": latest, "variant_kind": "adv_negation", "style": "legal",
                "path": f"{fund}/{doc['doc_id']}-v{latest}-adv_negation.md",
                "include_constraint_ids": vlat["constraint_ids"],
                "target_constraint_ids": [c for c in vlat["constraint_ids"] if not by_id[c]["distractor"]][:6],
                "instructions": "Express the targeted limits with negation-heavy and inverted phrasing (for example 'shall in no case be permitted to exceed', 'may not fall below', 'it is not the case that ... may exceed', 'no more than ... nor ...') without changing any threshold or its direction.",
            })
            carve = [c for c in vlat["constraint_ids"] if "carve_out" in by_id[c]]
            if carve:
                plan.append({
                    "rendering_id": f"{doc['doc_id']}-v{latest}-adv_unless", "doc_id": doc["doc_id"], "fund": fund,
                    "version": latest, "variant_kind": "adv_unless", "style": "narrative",
                    "path": f"{fund}/{doc['doc_id']}-v{latest}-adv_unless.md",
                    "include_constraint_ids": vlat["constraint_ids"], "target_constraint_ids": carve,
                    "instructions": "Place the carve-out clause in a separate paragraph two or more paragraphs away from the headline limit, introduced with 'unless', 'save that' or 'provided that', so the alternative threshold must be connected back to the rule.",
                })
        if dt == "esg_policy" and any("carve_out" in by_id[c] for c in vlat["constraint_ids"]):
            plan.append({
                "rendering_id": f"{doc['doc_id']}-v{latest}-adv_unless", "doc_id": doc["doc_id"], "fund": fund,
                "version": latest, "variant_kind": "adv_unless", "style": "narrative",
                "path": f"{fund}/{doc['doc_id']}-v{latest}-adv_unless.md",
                "include_constraint_ids": vlat["constraint_ids"],
                "target_constraint_ids": [c for c in vlat["constraint_ids"] if "carve_out" in by_id[c]],
                "instructions": "Place the carve-out clause in a separate paragraph away from the exclusion it modifies.",
            })
        if latest == 2 and dt in ("guidelines", "ips") :
            v1 = next(v for v in doc["versions"] if v["version"] == 1)
            changed_v1 = [c for c in v1["constraint_ids"] if by_id[c]["canonical_text"] not in {by_id[x]["canonical_text"] for x in vlat["constraint_ids"]}]
            plan.append({
                "rendering_id": f"{doc['doc_id']}-v2-adv_superseded", "doc_id": doc["doc_id"], "fund": fund,
                "version": 2, "variant_kind": "adv_superseded", "style": "legal",
                "path": f"{fund}/{doc['doc_id']}-v2-adv_superseded.md",
                "include_constraint_ids": vlat["constraint_ids"], "superseded_constraint_ids": changed_v1,
                "instructions": "A consolidated text that retains the superseded version-1 clauses verbatim, each clearly marked 'superseded with effect from 2026-04-01', immediately before or after the current clause. The current (version 2) rules are the binding ones.",
            })
        if dt == "corporate_actions_policy":
            plan.append({
                "rendering_id": f"{doc['doc_id']}-v{latest}-adv_crossref", "doc_id": doc["doc_id"], "fund": fund,
                "version": latest, "variant_kind": "adv_crossref", "style": "memo",
                "path": f"{fund}/{doc['doc_id']}-v{latest}-adv_crossref.md",
                "include_constraint_ids": vlat["constraint_ids"],
                "instructions": "Move every numeric threshold and every default election out of the body into a 'Schedule A' table at the end; the body refers to 'the default set out in Schedule A' and 'the deadline in Schedule A'. The single-security cross-reference to the Investment Guidelines stays as a cross-reference (do not restate the number).",
            })
    return plan


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--specs", default="data/specs")
    ap.add_argument("--out", default="data/specs/rendering_plan.json")
    a = ap.parse_args()
    cons = json.loads(Path(a.specs, "constraints.json").read_text())
    docs = json.loads(Path(a.specs, "documents.json").read_text())
    plan = build_plan(cons, docs)
    Path(a.out).write_text(json.dumps(plan, indent=1))
    from collections import Counter
    print(f"renderings={len(plan)}", dict(Counter(p['variant_kind'] for p in plan)), "per fund:", dict(Counter(p['fund'] for p in plan)))


if __name__ == "__main__":
    main()
