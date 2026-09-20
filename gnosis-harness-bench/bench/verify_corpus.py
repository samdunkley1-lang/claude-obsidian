"""Verify rendered documents against the spec: every binding threshold and scope must appear; no stray numbers.

Run: python -m bench.verify_corpus --specs data/specs --corpus data/corpus [--fund GTF] [--rendering ID]
Exit code 1 if any rendering fails. Prints one line per failure.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def num_forms(x: float) -> list[str]:
    s = f"{x:g}"
    forms = {s}
    if x == int(x):
        forms.add(f"{int(x)}.0")
    return sorted(forms)


def threshold_tokens(c: dict) -> list[list[str]]:
    """Return a list of alternatives-groups; each group is a list of acceptable surface forms, all groups must match."""
    t, u = c["threshold"], c["unit"]
    groups: list[list[str]] = []
    if isinstance(t, list):
        for x in t:
            groups.append([f"{x:g}"])
    elif isinstance(t, (int, float)):
        if u == "pct_nav":
            groups.append([f"{f}%" for f in num_forms(t)] + [f"{f} %" for f in num_forms(t)] + [f"{f} per cent" for f in num_forms(t)] + [f"{f} percent" for f in num_forms(t)])
        elif u == "bps":
            groups.append([f"{f} basis points" for f in num_forms(t)] + [f"{f} bps" for f in num_forms(t)] + [f"{f}bp" for f in num_forms(t)])
        else:
            groups.append(num_forms(t))
    elif isinstance(t, str):
        if t.startswith("benchmark_weight+"):
            pass
        elif c["type"] in ("restricted_list",):
            groups.append(["Restricted List"])
        elif c["type"] == "esg_exclusion":
            groups.append([c["scope"].get("target", t)])
        elif c["type"] == "ca_election_default":
            groups.append({"cash": ["cash"], "take_up": ["taken up", "take up", "take-up"], "decline": ["declined", "decline"]}.get(t, [t]))
        elif c["type"] == "valuation_lot_rule":
            groups.append({"odd_lot_pricing": ["odd-lot", "odd lot"], "committee_approval": ["Valuation Committee"]}.get(t, [t]))
        else:
            groups.append([t])
    if c.get("carve_out"):
        co = c["carve_out"]
        if isinstance(co.get("condition_value"), (int, float)) and not isinstance(co.get("condition_value"), bool):
            groups.append([f"{co['condition_value']:g}%", f"{co['condition_value']:g} per cent", f"{co['condition_value']:g} percent"])
        if isinstance(co.get("alt_threshold"), str) and co["alt_threshold"].startswith("benchmark_weight+"):
            plus = float(co["alt_threshold"].split("+")[1])
            groups.append([f"{plus:g} percentage point", f"{plus:g}%", f"{plus:g} per cent", f"{plus:g} percent"])
    return groups


def scope_tokens(c: dict) -> list[str]:
    tgt = c["scope"].get("target")
    if not tgt or c["type"] in ("esg_exclusion",):
        return []
    return [tgt]


def allowed_numbers(cons: list[dict]) -> set[str]:
    allowed = {"2025", "2026", "01", "04", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14", "15", "16", "17", "18", "19", "20", "0"}
    for c in cons:
        t = c["threshold"]
        vals = t if isinstance(t, list) else [t]
        for v in vals:
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                allowed.update(num_forms(float(v)))
        md = c.get("exception", {}).get("max_duration_days")
        if isinstance(md, (int, float)):
            allowed.update(num_forms(float(md)))
        co = c.get("carve_out") or {}
        for v in (co.get("condition_value"), ):
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                allowed.update(num_forms(float(v)))
        if isinstance(co.get("alt_threshold"), str) and "+" in co["alt_threshold"]:
            allowed.update(num_forms(float(co["alt_threshold"].split("+")[1])))
        # numbers embedded in canonical text (e.g. "25% of average daily volume", "five business days")
        for m in re.findall(r"\d+(?:\.\d+)?", c["canonical_text"]):
            allowed.add(m)
    return allowed


def check_rendering(r: dict, text: str, by_id: dict) -> list[str]:
    errs: list[str] = []
    norm = re.sub(r"\s+", " ", text).lower()
    cons = [by_id[i] for i in r["include_constraint_ids"]]
    for c in cons:
        for group in threshold_tokens(c):
            if not any(g.lower() in norm for g in group):
                errs.append(f"{r['rendering_id']}: missing threshold token for {c['id']} (any of {group[:4]})")
        for s in scope_tokens(c):
            if s.lower() not in norm:
                errs.append(f"{r['rendering_id']}: missing scope target '{s}' for {c['id']}")
    for cid in r.get("superseded_constraint_ids", []):
        c = by_id[cid]
        for group in threshold_tokens(c):
            if not any(g.lower() in norm for g in group):
                errs.append(f"{r['rendering_id']}: superseded clause {cid} must still appear (any of {group[:4]})")
        if "superseded" not in norm:
            errs.append(f"{r['rendering_id']}: the word 'superseded' must appear")
    allowed = allowed_numbers(cons + [by_id[i] for i in r.get("superseded_constraint_ids", [])])
    body = re.sub(r"\d{4}-\d{2}-\d{2}", " ", text)          # dates
    body = re.sub(r"\b(19|20)\d{2}\b", " ", body)             # years
    body = re.sub(r"(?m)^\s*#+.*$", " ", body)                # headings (section numbers)
    body = re.sub(r"(?m)^\s*\d+(\.\d+)*[\.\)]\s", " ", body)  # list/section numbering at line start
    body = re.sub(r"\bv\d\b", " ", body)                      # version labels
    body = re.sub(r"\b[A-Z]{2,4}-[a-z_]+-v\d-C\d\d\b", " ", body)  # constraint ids if quoted
    stray = sorted({m for m in re.findall(r"\d+(?:\.\d+)?", body) if m not in allowed})
    if stray:
        errs.append(f"{r['rendering_id']}: stray numbers not in spec: {stray}")
    wc = len(text.split())
    if wc < 350:
        errs.append(f"{r['rendering_id']}: too short ({wc} words; minimum 350)")
    return errs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--specs", default="data/specs")
    ap.add_argument("--corpus", default="data/corpus")
    ap.add_argument("--fund")
    ap.add_argument("--rendering")
    a = ap.parse_args()
    cons = json.loads(Path(a.specs, "constraints.json").read_text())
    plan = json.loads(Path(a.specs, "rendering_plan.json").read_text())
    by_id = {c["id"]: c for c in cons}
    failures = 0; checked = 0; missing = 0
    for r in plan:
        if a.fund and r["fund"] != a.fund: continue
        if a.rendering and r["rendering_id"] != a.rendering: continue
        p = Path(a.corpus, r["path"])
        if not p.exists():
            missing += 1; print(f"MISSING {r['rendering_id']} ({p})"); continue
        checked += 1
        errs = check_rendering(r, p.read_text(), by_id)
        for e in errs: print("FAIL", e)
        failures += bool(errs)
    print(f"checked={checked} failed={failures} missing={missing}")
    return 1 if (failures or missing) else 0


if __name__ == "__main__":
    sys.exit(main())
