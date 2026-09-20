"""Compare a blind re-extraction (no access to specs) with the spec labels for the same renderings.

Reports constraint-level precision, recall, F1 and Cohen's kappa on the binding/non-binding decision
per candidate rule. Run: python -m bench.audit_labels --blind data/labels/blind/EMF.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from bench.stats import cohens_kappa, wilson_interval


def norm(s):
    return (s or "").strip().lower()


def thr_equal(a, b) -> bool:
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(abs(float(x) - float(y)) < 1e-6 for x, y in zip(a, b))
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
        return abs(float(a) - float(b)) < 1e-6
    if isinstance(a, str) and isinstance(b, str):
        return norm(a) == norm(b) or norm(a) in norm(b) or norm(b) in norm(a)
    return False


def match(blind: dict, gold: dict) -> bool:
    if blind["type"] != gold["type"]:
        return False
    gt = gold["scope"].get("target")
    bt = blind.get("scope_target")
    if gt and (not bt or norm(gt) not in norm(bt) and norm(bt) not in norm(gt)):
        return False
    if gt is None and bt and gold["type"] not in ("esg_exclusion", "restricted_list", "ca_election_default", "valuation_lot_rule"):
        if norm(bt) not in ("fund", "whole fund", "the fund", "portfolio"):
            return False
    gthr = gold["threshold"]
    if isinstance(gthr, str) and gthr.startswith("benchmark_weight"):
        return True
    if gold["comparator"] in ("prohibited", "required"):
        return True  # scope + type identify these; numeric checked only if both numeric
    return thr_equal(blind.get("threshold"), gthr)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--blind", required=True)
    ap.add_argument("--specs", default="data/specs")
    a = ap.parse_args()
    blind = json.loads(Path(a.blind).read_text())
    cons = json.loads(Path(a.specs, "constraints.json").read_text())
    plan = json.loads(Path(a.specs, "rendering_plan.json").read_text())
    by_id = {c["id"]: c for c in cons}
    by_path = {Path(p["path"]).name: p for p in plan}
    tp = fp = fn = 0; kap_a: list[int] = []; kap_b: list[int] = []
    per_doc = {}
    for fname in sorted({b["doc"] for b in blind}):
        r = by_path[fname]
        gold_all = [by_id[i] for i in r["include_constraint_ids"]]
        gold_binding = [g for g in gold_all if not g["distractor"]]
        distractors = [g for g in gold_all if g["distractor"]]
        bl = [b for b in blind if b["doc"] == fname]
        used = set(); hits = 0
        for g in gold_binding:
            m = next((i for i, b in enumerate(bl) if i not in used and match(b, g)), None)
            if m is not None:
                used.add(m); hits += 1
        d_tp = hits; d_fn = len(gold_binding) - hits; d_fp = len(bl) - hits
        tp += d_tp; fn += d_fn; fp += d_fp
        # kappa on the binding decision: each gold row (binding or distractor) is an item; label_a = spec binding flag, label_b = extracted or not
        for g in gold_all:
            extracted = any(match(b, g) for b in bl)
            kap_a.append(int(not g["distractor"])); kap_b.append(int(extracted))
        per_doc[fname] = {"gold_binding": len(gold_binding), "distractors": len(distractors), "blind_rules": len(bl), "tp": d_tp, "fp": d_fp, "fn": d_fn,
                          "distractors_extracted": sum(1 for g in distractors if any(match(b, g) for b in bl))}
    prec = tp / (tp + fp) if tp + fp else float("nan"); rec = tp / (tp + fn) if tp + fn else float("nan")
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    k = cohens_kappa(kap_a, kap_b)
    _, rlo, rhi = wilson_interval(tp, tp + fn)
    for d, v in per_doc.items():
        print(f"{d}: gold={v['gold_binding']} blind={v['blind_rules']} tp={v['tp']} fp={v['fp']} fn={v['fn']} distractors_extracted={v['distractors_extracted']}/{v['distractors']}")
    print(f"TOTAL precision={prec:.3f} recall={rec:.3f} [{rlo:.3f},{rhi:.3f}] f1={f1:.3f} kappa(binding decision)={k['kappa']:.3f} [{k['ci_lo']:.3f},{k['ci_hi']:.3f}] n_items={k['n']}")


if __name__ == "__main__":
    main()
