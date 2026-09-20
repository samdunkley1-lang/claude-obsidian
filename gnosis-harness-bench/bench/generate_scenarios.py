"""Seeded scenario generator for the verdict task.

For every fund and decision type it builds proposals aimed at specific outcomes (pass, warn band,
soft warn, breach, hard block, carve-out, missing input, no applicable rule) and asserts that the
reference engine produces the intended overall verdict. Then it derives variants: paraphrase,
adversarial renderings, and as-of-prior-version scenarios with both document versions supplied.

Run: python -m bench.generate_scenarios --specs data/specs --out data/scenarios/scenarios.jsonl
"""
from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from pathlib import Path

from bench.generate_specs import P
from bench.reference_engine import evaluate, version_in_force
from bench.schema import ALL_DECISION_TYPES, FUNDS, validate_scenario

AS_OF = "2026-06-15"
AS_OF_PRIOR = "2026-02-15"

TICKERS = {
    "GTF": [("NVDA", "NVIDIA", "Semiconductors", "United States"), ("MSFT", "Microsoft", "Software", "United States"),
            ("TSM", "TSMC", "Semiconductors", "Taiwan"), ("ASML", "ASML", "Hardware", "Netherlands")],
    "EIF": [("ULVR", "Unilever", "Consumer Staples", "United Kingdom"), ("SIE", "Siemens", "Industrials", "Germany"),
            ("BNP", "BNP Paribas", "Financials", "France"), ("ENEL", "Enel", "Utilities", "Italy")],
    "DGF": [("AAPL", "Apple", "Technology", "United States"), ("TM", "Toyota", "Consumer Discretionary", "Japan"),
            ("SHEL", "Shell", "Energy", "United Kingdom"), ("NOVN", "Novartis", "Healthcare", "Switzerland")],
    "CBF": [("VZ33", "Verizon", "Telecommunications", "United States"), ("BARC30", "Barclays", "Financials", "United Kingdom"),
            ("ENEL31", "Enel", "Utilities", "Italy"), ("BP29", "BP", "Energy", "United Kingdom")],
    "EMF": [("TCEHY", "Tencent", "Technology", "China"), ("RELI", "Reliance Industries", "Materials", "India"),
            ("VALE", "Vale", "Materials", "Brazil"), ("SCOM", "Safaricom", "Telecommunications", "Kenya")],
}
DOC_TYPES = ["ips", "guidelines", "derivatives_policy", "esg_policy", "liquidity_policy", "valuation_policy",
             "counterparty_policy", "corporate_actions_policy"]


class Ctx:
    def __init__(self, constraints: list[dict], documents: list[dict], plan: list[dict]):
        self.cons = constraints; self.docs = documents; self.plan = plan
        self.by_id = {c["id"]: c for c in constraints}
        self.doc_by_id = {d["doc_id"]: d for d in documents}
        self.rendering_ids = {p["rendering_id"] for p in plan}

    def limit(self, fund: str, ctype: str, target: str | None, as_of: str, level: str | None = None):
        for dt in DOC_TYPES:
            d = self.doc_by_id[f"{fund}-{dt}"]
            v = version_in_force(d, as_of)
            ver = next(x for x in d["versions"] if x["version"] == v)
            for cid in ver["constraint_ids"]:
                c = self.by_id[cid]
                if c["distractor"] or c["type"] != ctype: continue
                if target is not None and c["scope"].get("target") != target: continue
                if level is not None and c["scope"]["level"] != level: continue
                if target is None and c["scope"].get("target") is not None and level is None: continue
                return c
        raise KeyError((fund, ctype, target, as_of))

    def renderings_for(self, fund: str, as_of: str, swaps: dict[str, str] | None = None, both_versions: bool = False) -> list[str]:
        out = []
        for dt in DOC_TYPES:
            d = self.doc_by_id[f"{fund}-{dt}"]
            v = version_in_force(d, as_of)
            rid = f"{d['doc_id']}-v{v}-canonical"
            if swaps and dt in swaps:
                rid = swaps[dt]
            assert rid in self.rendering_ids, rid
            out.append(rid)
            if both_versions and len(d["versions"]) > 1:
                for ver in d["versions"]:
                    alt = f"{d['doc_id']}-v{ver['version']}-canonical"
                    if alt not in out: out.append(alt)
        return out


def baseline_portfolio(fund: str, as_of: str, ctx: Ctx) -> dict:
    p = P[fund]
    cash_lo, cash_hi = p["cash"]
    ex: dict[str, float] = {"cash": (cash_lo + cash_hi) / 2}
    single = ctx.limit(fund, "single_name_max", None, as_of, level="fund")["threshold"]
    for i, (t, iss, sec, cty) in enumerate(TICKERS[fund]):
        w = round(single * (0.6 - 0.1 * i), 2)
        ex[f"single_name:{t}"] = w; ex[f"issuer:{iss}"] = w
    for sec, lim in p["sectors"]:
        ex[f"sector:{sec}"] = round(lim * 0.6, 2)
    for cty, lim in p["countries"]:
        ex[f"country:{cty}"] = round(lim * 0.6, 2)
    if p["frontier"] is not None: ex["country:Frontier markets"] = round(p["frontier"] * 0.5, 2)
    if p["duration"]: ex["duration"] = round(sum(p["duration"]) / 2, 2)
    if p["hy"]: ex["hy"] = round(p["hy"] * 0.5, 2)
    if p["fx"]: ex["unhedged_fx"] = round(p["fx"] * 0.5, 2)
    ex["derivatives_notional"] = round(p["deriv"] * 0.4, 2)
    ex["counterparty:Goldman Sachs"] = round(p["cpty"] * 0.4, 2)
    ex["illiquid"] = round(p["illiquid"] * 0.4, 2)
    ex["liquid_5d"] = round(p["liq"] + 12, 2)
    sleeve_name, sleeve_lim = p["sleeve"]
    ex[f"sleeve:{sleeve_name}:PRIV1"] = round(sleeve_lim * 0.5, 2); ex["single_name:PRIV1"] = ex[f"sleeve:{sleeve_name}:PRIV1"]
    return {"nav_musd": 1200.0, "exposures": ex, "holdings_count": p["positions"] + 10, "as_of": as_of}


def recipes(fund: str, as_of: str, ctx: Ctx) -> list[tuple[str, str, dict, str, list[str]]]:
    """Return (decision_type, label, fields, intended_overall, tags)."""
    p = P[fund]; R: list = []
    t0, iss0, sec0, cty0 = TICKERS[fund][0]
    t1, iss1, sec1, cty1 = TICKERS[fund][1]
    single_c = ctx.limit(fund, "single_name_max", None, as_of, level="fund"); L = single_c["threshold"]
    cur = round(L * 0.6, 2)
    base = dict(ticker=t0, issuer=iss0, sector=sec0, country=cty0, current_weight=cur, benchmark_weight=1.0, restricted=False, funded_from_cash=False)
    sec_lim = dict(p["sectors"])[sec0] if sec0 in dict(p["sectors"]) else None
    # 1 single_name_overweight
    R += [("single_name_overweight", "pass", {**base, "target_weight": round(L * 0.75, 2)}, "pass", ["single_name"]),
          ("single_name_overweight", "warn_band", {**base, "target_weight": round(L * 0.93, 2)}, "warn", ["single_name", "warn_band"]),
          ("single_name_overweight", "breach", {**base, "target_weight": round(L * 1.15, 2)}, "breach", ["single_name"]),
          ("single_name_overweight", "hard_restricted", {**base, "target_weight": round(L * 0.75, 2), "restricted": True}, "hard_block", ["hard_gate", "restricted"]),
          ("single_name_overweight", "missing_target", {k: v for k, v in base.items()}, "warn", ["missing_input"])]
    if single_c.get("carve_out"):
        bw = single_c["carve_out"]["condition_value"]; plus = float(single_c["carve_out"]["alt_threshold"].split("+")[1])
        alt = bw + 5 + plus
        issuer_lim = ctx.limit(fund, "issuer_max", None, as_of)["threshold"]
        carve_target = round(min(alt * 0.85, issuer_lim * 0.85), 2)
        assert carve_target > L, (fund, carve_target, L)
        R.append(("single_name_overweight", "carve_out_pass", {**base, "benchmark_weight": bw + 5, "target_weight": carve_target}, "pass", ["carve_out"]))
        R.append(("single_name_overweight", "carve_out_breach", {**base, "benchmark_weight": bw + 5, "target_weight": round(alt + 0.5, 2)}, "breach", ["carve_out"]))
    # 2 single_name_new_position
    nb = dict(ticker="NEWCO", issuer="Newco Holdings", sector=sec1, country=cty1, current_weight=0.0, benchmark_weight=0.5, restricted=False, funded_from_cash=False)
    if fund in ("CBF", "DGF"): nb["rating"] = "BBB"
    R += [("single_name_new_position", "pass", {**nb, "target_weight": round(L * 0.5, 2)}, "pass", ["new_position"]),
          ("single_name_new_position", "warn_band", {**nb, "target_weight": round(L * 0.92, 2)}, "warn", ["new_position", "warn_band"]),
          ("single_name_new_position", "breach", {**nb, "target_weight": round(L * 1.1, 2)}, "breach", ["new_position"]),
          ("single_name_new_position", "esg_hard", {**nb, "target_weight": round(L * 0.5, 2), "esg_involvement": ["controversial weapons"]}, "hard_block", ["hard_gate", "esg"]),
          ("single_name_new_position", "coal_breach", {**nb, "target_weight": round(L * 0.5, 2), "thermal_coal_revenue_pct": p["coal"] + 15}, "breach", ["esg"]),
          ("single_name_new_position", "ungc_breach", {**nb, "target_weight": round(L * 0.5, 2), "esg_involvement": ["UN Global Compact violators"]}, "breach", ["esg"])]
    if fund == "CBF":
        R.append(("single_name_new_position", "coal_green_carve_pass", {**nb, "target_weight": round(L * 0.5, 2), "thermal_coal_revenue_pct": 45.0, "certified_green_bond": True}, "pass", ["carve_out", "esg"]))
    if p["tobacco"]:
        R.append(("single_name_new_position", "tobacco_breach", {**nb, "target_weight": round(L * 0.5, 2), "esg_involvement": ["tobacco"]}, "breach", ["esg"]))
    if p["rating"]:
        R.append(("single_name_new_position", "rating_breach", {**nb, "target_weight": round(L * 0.5, 2), "rating": "CCC+"}, "breach", ["credit"]))
    # 3 exit_sell
    cash_lo, cash_hi = p["cash"]; cash_max = ctx.limit(fund, "cash_max", None, as_of)["threshold"]
    cash_mid = (cash_lo + cash_hi) / 2
    R += [("exit_sell", "pass", {**base, "funded_from_cash": False, "target_weight": 0.0}, "pass", ["exit"]),
          ("exit_sell", "cash_max_breach", {**base, "funded_from_cash": True, "current_weight": round(cash_max - cash_mid + 1.0, 2), "target_weight": 0.0}, "breach", ["exit", "cash"])]
    # 4 sector_tilt (ips sector)
    s0, s0lim = p["sectors"][0]
    R += [("sector_tilt", "pass", {"sector": s0, "target_weight": round(s0lim * 0.75, 2), "funded_from_cash": False}, "pass", ["sector"]),
          ("sector_tilt", "warn_band", {"sector": s0, "target_weight": round(s0lim * 0.93, 2), "funded_from_cash": False}, "warn", ["sector", "warn_band"]),
          ("sector_tilt", "breach", {"sector": s0, "target_weight": round(s0lim * 1.1, 2), "funded_from_cash": False}, "breach", ["sector"])]
    # 5 country_tilt (guidelines country)
    c1, c1lim = p["countries"][1]
    R += [("country_tilt", "pass", {"country": c1, "target_weight": round(c1lim * 0.75, 2), "funded_from_cash": False}, "pass", ["country"]),
          ("country_tilt", "warn_band", {"country": c1, "target_weight": round(c1lim * 0.93, 2), "funded_from_cash": False}, "warn", ["country", "warn_band"]),
          ("country_tilt", "breach", {"country": c1, "target_weight": round(c1lim * 1.1, 2), "funded_from_cash": False}, "breach", ["country"])]
    # 6 cash_level_change
    swing = ctx.limit(fund, "swing_threshold", None, as_of)["threshold"]
    R += [("cash_level_change", "pass", {"target_cash": round(cash_mid, 2), "net_flow_pct": 0.2, "swing_applied": False}, "pass", ["cash"]),
          ("cash_level_change", "cash_max_warn", {"target_cash": round(cash_max * 0.93, 2), "net_flow_pct": 0.2, "swing_applied": False}, "warn", ["cash", "warn_band"]),
          ("cash_level_change", "cash_max_breach", {"target_cash": round(cash_max * 1.15, 2), "net_flow_pct": 0.2, "swing_applied": False}, "breach", ["cash"]),
          ("cash_level_change", "swing_breach", {"target_cash": round(cash_mid, 2), "net_flow_pct": round(swing + 1.0, 2), "swing_applied": False}, "breach", ["liquidity", "swing"]),
          ("cash_level_change", "swing_pass", {"target_cash": round(cash_mid, 2), "net_flow_pct": round(swing + 1.0, 2), "swing_applied": True}, "pass", ["liquidity", "swing"]),
          ("cash_level_change", "missing_target", {"net_flow_pct": 0.2, "swing_applied": False}, "warn", ["missing_input"])]
    if cash_lo > 0:
        R.append(("cash_level_change", "cash_min_breach", {"target_cash": round(max(cash_lo - 0.5, 0.0), 2), "net_flow_pct": 0.1, "swing_applied": False}, "breach", ["cash"]))
    # 7 duration_extension
    if p["duration"]:
        lo, hi = ctx.limit(fund, "duration_band", None, as_of)["threshold"]
        edge = 0.1 * (hi - lo)
        R += [("duration_extension", "pass", {"target_duration": round((lo + hi) / 2 + 0.3, 2)}, "pass", ["duration"]),
              ("duration_extension", "warn_band", {"target_duration": round(hi - edge * 0.5, 2)}, "warn", ["duration", "warn_band"]),
              ("duration_extension", "breach", {"target_duration": round(hi + 0.6, 2)}, "breach", ["duration"]),
              ("duration_extension", "missing_target", {"current_duration": round((lo + hi) / 2, 2)}, "warn", ["missing_input"])]
    else:
        R.append(("duration_extension", "no_rule_control", {"current_duration": 0.0, "target_duration": 1.5}, "pass", ["no_applicable_rule"]))
    # 8 credit_quality_shift
    if p["hy"]:
        hy = ctx.limit(fund, "hy_max", None, as_of)["threshold"]
        R += [("credit_quality_shift", "pass", {"hy_target": round(hy * 0.7, 2), "min_rating_added": "BB"}, "pass", ["credit"]),
              ("credit_quality_shift", "warn_band", {"hy_target": round(hy * 0.95, 2), "min_rating_added": "BB"}, "warn", ["credit", "warn_band"]),
              ("credit_quality_shift", "breach", {"hy_target": round(hy * 1.2, 2), "min_rating_added": "BB"}, "breach", ["credit"]),
              ("credit_quality_shift", "rating_breach", {"hy_target": round(hy * 0.7, 2), "min_rating_added": "CCC"}, "breach", ["credit"])]
    else:
        R.append(("credit_quality_shift", "no_rule_control", {"hy_target": 2.0, "min_rating_added": "BB"}, "pass", ["no_applicable_rule"]))
    # 9 fx_hedge_ratio_change
    if p["fx"]:
        fx = ctx.limit(fund, "unhedged_fx_max", None, as_of)["threshold"]
        R += [("fx_hedge_ratio_change", "pass", {"unhedged_target": round(fx * 0.7, 2)}, "pass", ["fx"]),
              ("fx_hedge_ratio_change", "warn_band", {"unhedged_target": round(fx * 0.95, 2)}, "warn", ["fx", "warn_band"]),
              ("fx_hedge_ratio_change", "breach", {"unhedged_target": round(fx * 1.25, 2)}, "breach", ["fx"])]
    else:
        R.append(("fx_hedge_ratio_change", "no_rule_control", {"unhedged_target": 40.0}, "pass", ["no_applicable_rule"]))
    # 10 derivatives_overlay
    dn = ctx.limit(fund, "derivatives_notional_max", None, as_of, level="fund")["threshold"]
    cp = ctx.limit(fund, "counterparty_max", "any single derivatives counterparty", as_of)["threshold"]
    cprat = ctx.limit(fund, "credit_min_rating", "derivatives counterparty", as_of)["threshold"]
    d0 = dict(purpose="hedging", counterparty="Goldman Sachs", counterparty_rating="A+", counterparty_target=round(cp * 0.5, 2), affiliated=False, uncollateralised_exposure=1.0)
    R += [("derivatives_overlay", "pass", {**d0, "notional_target": round(dn * 0.7, 2)}, "pass", ["derivatives"]),
          ("derivatives_overlay", "warn_band", {**d0, "notional_target": round(dn * 0.95, 2)}, "warn", ["derivatives", "warn_band"]),
          ("derivatives_overlay", "breach", {**d0, "notional_target": round(dn * 1.2, 2)}, "breach", ["derivatives"]),
          ("derivatives_overlay", "cpty_breach", {**d0, "notional_target": round(dn * 0.7, 2), "counterparty_target": round(cp * 1.2, 2)}, "breach", ["counterparty"]),
          ("derivatives_overlay", "cpty_rating_breach", {**d0, "notional_target": round(dn * 0.7, 2), "counterparty": "Regional Bank", "counterparty_rating": "BBB-", "counterparty_target": round(cp * 0.3, 2)}, "breach", ["counterparty", "credit"]),
          ("derivatives_overlay", "affiliated_hard", {**d0, "notional_target": round(dn * 0.7, 2), "counterparty": "Midland Securities", "affiliated": True}, "hard_block", ["hard_gate", "conflict_of_interest"]),
          ("derivatives_overlay", "uncollateralised_breach", {**d0, "notional_target": round(dn * 0.7, 2), "uncollateralised_exposure": 7.0}, "breach", ["counterparty"]),
          ("derivatives_overlay", "missing_notional", {**d0}, "warn", ["missing_input"])]
    if p["deriv_nonhedge"] == "prohibited":
        R.append(("derivatives_overlay", "nonhedge_breach", {**d0, "notional_target": round(dn * 0.7, 2), "purpose": "non_hedging"}, "breach", ["derivatives"]))
    # 11 corporate_action_election
    ca = dict(ticker=t0, issuer=iss0, sector=sec0, country=cty0, current_weight=cur, restricted=False, days_before_deadline=4, funded_from_cash=False)
    R += [("corporate_action_election", "cash_pass", {**ca, "event_type": "scrip_dividend", "election": "cash", "rationale_provided": False, "post_election_weight": cur}, "pass", ["corporate_action"]),
          ("corporate_action_election", "scrip_no_rationale", {**ca, "event_type": "scrip_dividend", "election": "scrip", "rationale_provided": False, "post_election_weight": round(cur + 0.2, 2)}, "breach", ["corporate_action"]),
          ("corporate_action_election", "scrip_over_limit", {**ca, "event_type": "scrip_dividend", "election": "scrip", "rationale_provided": True, "post_election_weight": round(L * 1.05, 2)}, "breach", ["corporate_action", "single_name"]),
          ("corporate_action_election", "tender_no_cio", {**ca, "event_type": "tender_offer", "election": "tender", "cio_approved": False}, "breach", ["corporate_action"]),
          ("corporate_action_election", "tender_cio_pass", {**ca, "event_type": "tender_offer", "election": "tender", "cio_approved": True}, "pass", ["corporate_action"]),
          ("corporate_action_election", "rights_lapse_no_rationale", {**ca, "event_type": "rights_issue", "election": "lapse", "rationale_provided": False}, "breach", ["corporate_action"]),
          ("corporate_action_election", "deadline_warn", {**ca, "event_type": "rights_issue", "election": "take_up", "days_before_deadline": 1}, "warn", ["corporate_action", "soft"]),
          ("corporate_action_election", "scrip_restricted_hard", {**ca, "event_type": "scrip_dividend", "election": "scrip", "rationale_provided": True, "restricted": True, "post_election_weight": round(cur + 0.2, 2)}, "hard_block", ["hard_gate", "restricted"])]
    if p["ca_scrip_ok"]:
        R.append(("corporate_action_election", "scrip_ok_pass", {**ca, "event_type": "scrip_dividend", "election": "scrip", "rationale_provided": True, "post_election_weight": round(cur + 0.2, 2)}, "pass", ["corporate_action"]))
    else:
        R.append(("corporate_action_election", "scrip_not_permitted", {**ca, "event_type": "scrip_dividend", "election": "scrip", "rationale_provided": True, "post_election_weight": round(cur + 0.2, 2)}, "breach", ["corporate_action"]))
    # 12 guideline_exception_request
    ill = ctx.limit(fund, "illiquid_max", None, as_of)["threshold"]
    R += [("guideline_exception_request", "single_name_20d", {"constraint_type": "single_name_max", "scope_level": "fund", "requested_exposure": round(L * 1.2, 2), "duration_days": 20}, "breach", ["exception"]),
          ("guideline_exception_request", "single_name_45d_reject", {"constraint_type": "single_name_max", "scope_level": "fund", "requested_exposure": round(L * 1.2, 2), "duration_days": 45}, "breach", ["exception", "reject"]),
          ("guideline_exception_request", "illiquid_risk_path", {"constraint_type": "illiquid_max", "scope_level": "fund", "requested_exposure": round(ill * 1.3, 2), "duration_days": 15}, "breach", ["exception", "risk"]),
          ("guideline_exception_request", "within_limit_control", {"constraint_type": "single_name_max", "scope_level": "fund", "requested_exposure": round(L * 0.8, 2), "duration_days": 10}, "pass", ["exception", "control"])]
    # 13 valuation_mark_override
    R += [("valuation_mark_override", "odd_lot_breach", {"asset_class": "CMO", "lot_size": "odd", "level": 2, "days_stale": 1, "mark_source": "institutional_lot", "committee_approved": False}, "breach", ["valuation"]),
          ("valuation_mark_override", "odd_lot_pass", {"asset_class": "CMO", "lot_size": "odd", "level": 2, "days_stale": 1, "mark_source": "odd_lot", "committee_approved": False}, "pass", ["valuation"]),
          ("valuation_mark_override", "level3_unapproved", {"asset_class": "private loan", "lot_size": "round", "level": 3, "days_stale": 0, "mark_source": "model", "committee_approved": False}, "breach", ["valuation"]),
          ("valuation_mark_override", "level3_approved", {"asset_class": "private loan", "lot_size": "round", "level": 3, "days_stale": 0, "mark_source": "model", "committee_approved": True}, "pass", ["valuation"]),
          ("valuation_mark_override", "stale_unapproved", {"asset_class": "corporate bond", "lot_size": "round", "level": 2, "days_stale": 8, "mark_source": "broker_quote", "committee_approved": False}, "breach", ["valuation"]),
          ("valuation_mark_override", "missing_fields", {"asset_class": "corporate bond", "lot_size": "round"}, "warn", ["missing_input"])]
    return R


def build(ctx: Ctx, seed: int = 0) -> list[dict]:
    rng = random.Random(seed)
    out: list[dict] = []
    doc_ids_for = lambda f: [f"{f}-{dt}" for dt in DOC_TYPES]
    for fund in FUNDS:
        port = baseline_portfolio(fund, AS_OF, ctx)
        for dt, label, fields, intended, tags in recipes(fund, AS_OF, ctx):
            sid = f"{fund}-{dt}-{label}"
            like = {"fund": fund, "as_of": AS_OF, "proposal": {"decision_type": dt, "fields": fields}, "portfolio": port, "doc_ids": doc_ids_for(fund)}
            gold = evaluate(like, ctx.cons, ctx.docs)
            assert gold["overall"] == intended, (sid, gold["overall"], intended, gold["verdicts"], gold["_reasons"])
            gold.pop("_reasons")
            sc = {"scenario_id": sid, "fund": fund, "decision_type": dt, "as_of": AS_OF,
                  "proposal": like["proposal"], "portfolio": port, "documents": ctx.renderings_for(fund, AS_OF),
                  "gold": gold, "variant_kind": "canonical", "variant_of": None, "tags": tags + [intended, f"verb:{gold['recommendation_verb']}"]}
            validate_scenario(sc); out.append(sc)
    canonical = list(out)
    # ---- rendering-swap variants (same gold) ----------------------------------------------
    def swap_variant(sc: dict, doc_type: str, kind: str) -> dict | None:
        d = ctx.doc_by_id[f"{sc['fund']}-{doc_type}"]
        v = version_in_force(d, sc["as_of"])
        rid = f"{d['doc_id']}-v{v}-{kind}"
        if rid not in ctx.rendering_ids: return None
        new = json.loads(json.dumps(sc))
        new["scenario_id"] = f"{sc['scenario_id']}__{kind}_{doc_type}"
        new["documents"] = ctx.renderings_for(sc["fund"], sc["as_of"], swaps={doc_type: rid})
        new["variant_kind"] = kind; new["variant_of"] = sc["scenario_id"]; new["tags"] = sc["tags"] + [f"variant:{kind}"]
        return new
    hit_doc_types = lambda sc: {ctx.by_id[i]["doc_id"].split("-", 1)[1] for i in sc["gold"]["rules_hit"]}
    for sc in canonical:
        touched = hit_doc_types(sc) or {"guidelines"}
        for dtp in sorted(touched):
            if dtp in ("guidelines", "ips", "esg_policy"):
                v = swap_variant(sc, dtp, "paraphrase");  out.append(v) if v else None
            if dtp == "guidelines" and any(t in sc["tags"] for t in ("single_name", "country", "new_position", "exception")):
                v = swap_variant(sc, dtp, "adv_negation"); out.append(v) if v else None
            if "carve_out" in sc["tags"] and dtp in ("guidelines", "esg_policy"):
                v = swap_variant(sc, dtp, "adv_unless"); out.append(v) if v else None
            if dtp in ("guidelines", "ips"):
                v = swap_variant(sc, dtp, "adv_superseded"); out.append(v) if v else None
            if dtp == "corporate_actions_policy":
                v = swap_variant(sc, dtp, "adv_crossref"); out.append(v) if v else None
    # ---- as-of-prior-version scenarios (gold differs by version) ----------------------------
    for fund in FUNDS:
        port = baseline_portfolio(fund, AS_OF_PRIOR, ctx)
        for dt in DOC_TYPES:
            d = ctx.doc_by_id[f"{fund}-{dt}"]
            if len(d["versions"]) < 2: continue
            v1 = next(x for x in d["versions"] if x["version"] == 1); v2 = next(x for x in d["versions"] if x["version"] == 2)
            for cid1 in v1["constraint_ids"]:
                c1 = ctx.by_id[cid1]
                if c1["distractor"]: continue
                c2 = next((ctx.by_id[i] for i in v2["constraint_ids"] if ctx.by_id[i]["type"] == c1["type"] and ctx.by_id[i]["scope"] == c1["scope"] and not ctx.by_id[i]["distractor"]), None)
                if not c2 or c2["threshold"] == c1["threshold"]: continue
                for as_of, intended_note in ((AS_OF_PRIOR, "v1"), (AS_OF, "v2")):
                    fields, dtype = prior_version_recipe(fund, c1, c2, ctx)
                    if fields is None: continue
                    sid = f"{fund}-{dtype}-asof_{intended_note}_{c1['type']}"
                    like = {"fund": fund, "as_of": as_of, "proposal": {"decision_type": dtype, "fields": fields}, "portfolio": {**port, "as_of": as_of}, "doc_ids": doc_ids_for(fund)}
                    gold = evaluate(like, ctx.cons, ctx.docs); gold.pop("_reasons")
                    sc = {"scenario_id": sid, "fund": fund, "decision_type": dtype, "as_of": as_of, "proposal": like["proposal"],
                          "portfolio": like["portfolio"], "documents": ctx.renderings_for(fund, as_of, both_versions=True),
                          "gold": gold, "variant_kind": "as_of_prior_version" if intended_note == "v1" else "canonical",
                          "variant_of": None if intended_note == "v1" else None, "tags": ["as_of", intended_note, c1["type"], gold["overall"], f"verb:{gold['recommendation_verb']}", "both_versions_supplied"]}
                    validate_scenario(sc); out.append(sc)
    # pair the v1/v2 as-of scenarios so paraphrase-style robustness can compare them
    for sc in out:
        if sc["variant_kind"] == "as_of_prior_version":
            sc["variant_of"] = sc["scenario_id"].replace("asof_v1", "asof_v2")
    ids = [s["scenario_id"] for s in out]
    assert len(ids) == len(set(ids)), "duplicate scenario ids"
    rng.shuffle(out); out.sort(key=lambda s: s["scenario_id"])
    return out


def prior_version_recipe(fund: str, c1: dict, c2: dict, ctx: Ctx):
    """Build a proposal whose verdict differs between the v1 and v2 thresholds."""
    t = c1["type"]; a, b = c1["threshold"], c2["threshold"]
    t0, iss0, sec0, cty0 = TICKERS[fund][0]
    if t == "single_name_max":
        lo, hi = sorted([a, b]); target = round(lo + 0.6 * (hi - lo) + 0.05, 2)  # above the lower limit, below the higher
        return dict(ticker=t0, issuer=iss0, sector=sec0, country=cty0, current_weight=round(lo * 0.5, 2), benchmark_weight=1.0, restricted=False, funded_from_cash=False, target_weight=target), "single_name_overweight"
    if t == "issuer_max":
        lo, hi = sorted([a, b]); target = round(lo + 0.6 * (hi - lo) + 0.05, 2)
        return dict(ticker=t0, issuer=iss0, sector=sec0, country=cty0, current_weight=round(lo * 0.5, 2), benchmark_weight=1.0, restricted=False, funded_from_cash=False, target_weight=target), "single_name_overweight"
    if t == "cash_max":
        lo, hi = sorted([a, b]); return dict(target_cash=round(lo + 0.6 * (hi - lo), 2), net_flow_pct=0.1, swing_applied=False), "cash_level_change"
    if t == "illiquid_max":
        lo, hi = sorted([a, b]); return dict(constraint_type="illiquid_max", scope_level="fund", requested_exposure=round(lo + 0.6 * (hi - lo), 2), duration_days=10), "guideline_exception_request"
    if t == "esg_exclusion" and c1["scope"].get("target") == "thermal coal":
        lo, hi = sorted([a, b]); return dict(ticker="COALCO", issuer="Coalco", sector=sec0, country=cty0, current_weight=0.0, benchmark_weight=0.1, restricted=False, funded_from_cash=False, target_weight=1.0, thermal_coal_revenue_pct=round(lo + 0.5 * (hi - lo), 1)), "single_name_new_position"
    if t == "derivatives_notional_max" and c1["scope"]["level"] == "fund":
        lo, hi = sorted([a, b]); return dict(purpose="hedging", counterparty="Goldman Sachs", counterparty_rating="A+", counterparty_target=1.0, affiliated=False, uncollateralised_exposure=1.0, notional_target=round(lo + 0.6 * (hi - lo), 2)), "derivatives_overlay"
    if t == "swing_threshold":
        lo, hi = sorted([a, b]); return dict(target_cash=5.0 if fund != "EIF" else 2.5, net_flow_pct=round(lo + 0.5 * (hi - lo), 2), swing_applied=False), "cash_level_change"
    if t == "duration_band":
        (lo1, hi1), (lo2, hi2) = a, b
        if lo1 != lo2: return dict(target_duration=round((lo1 + lo2) / 2, 2)), "duration_extension"
        if hi1 != hi2: return dict(target_duration=round((hi1 + hi2) / 2, 2)), "duration_extension"
    if t == "hy_max":
        lo, hi = sorted([a, b]); return dict(hy_target=round(lo + 0.6 * (hi - lo), 2), min_rating_added="BB"), "credit_quality_shift"
    if t == "counterparty_max" and c1["scope"].get("target") == "any single securities lending counterparty":
        lo, hi = sorted([a, b]); return dict(constraint_type="counterparty_max", scope_level="issuer", scope_target=c1["scope"]["target"], requested_exposure=round(lo + 0.6 * (hi - lo), 2), duration_days=10), "guideline_exception_request"
    if t == "turnover_max":
        lo, hi = sorted([a, b]); return dict(ticker=t0, issuer=iss0, sector=sec0, country=cty0, current_weight=2.0, target_weight=2.5, benchmark_weight=1.0, restricted=False, funded_from_cash=False, turnover_post=round(lo + 0.6 * (hi - lo), 2)), "single_name_overweight"
    if t == "liquidity_min_daily" and c1["scope"]["level"] == "fund":
        lo, hi = sorted([a, b]); return dict(constraint_type="liquidity_min_daily", scope_level="fund", requested_exposure=round(lo + 0.4 * (hi - lo), 2), duration_days=10), "guideline_exception_request"
    return None, None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--specs", default="data/specs"); ap.add_argument("--out", default="data/scenarios/scenarios.jsonl"); ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    cons = json.loads(Path(a.specs, "constraints.json").read_text()); docs = json.loads(Path(a.specs, "documents.json").read_text())
    plan = json.loads(Path(a.specs, "rendering_plan.json").read_text())
    ctx = Ctx(cons, docs, plan)
    scenarios = build(ctx, a.seed)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, "w") as f:
        for s in scenarios: f.write(json.dumps(s) + "\n")
    print(f"scenarios={len(scenarios)}")
    print("by variant:", dict(Counter(s["variant_kind"] for s in scenarios)))
    print("by overall:", dict(Counter(s["gold"]["overall"] for s in scenarios)))
    print("by verb:", dict(Counter(s["gold"]["recommendation_verb"] for s in scenarios)))
    print("by decision type:", dict(Counter(s["decision_type"] for s in scenarios)))
    print("hard gates:", sum(1 for s in scenarios if s["gold"]["overall"] == "hard_block"), "| both-versions:", sum(1 for s in scenarios if "both_versions_supplied" in s["tags"]))


if __name__ == "__main__":
    main()
