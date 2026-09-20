"""Seeded generator of structured rule specs (the ground truth) for the Midland Capital fixture.

Five funds, eight policy documents each, version 1 effective 2025-01-01. About half the
documents receive a version 2 amendment effective 2026-04-01 that changes one or two
thresholds. Every constraint carries the canonical sentence a renderer must reproduce in
substance, so labels are exact by construction. Distractor rows are non-binding lookalikes
(targets, expectations, history) that an extractor must not return.

Run: python -m bench.generate_specs --out data/specs
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from bench.schema import FUNDS, FUND_NAMES, validate_constraint

V1_DATE = "2025-01-01"
V2_DATE = "2026-04-01"

APPROVERS_BREACH = ["PM", "CIO", "Compliance"]
APPROVERS_RISK = ["PM", "CIO", "Risk"]
APPROVERS_VAL = ["PM", "ValuationCommittee"]

EXC_STD = {"allowed": True, "approvers": APPROVERS_BREACH, "four_eyes": True, "max_duration_days": 30}
EXC_RISK = {"allowed": True, "approvers": APPROVERS_RISK, "four_eyes": True, "max_duration_days": 30}
EXC_VAL = {"allowed": True, "approvers": APPROVERS_VAL, "four_eyes": True}
EXC_NONE = {"allowed": False, "approvers": [], "four_eyes": False}

# Fund parameters. Units: pct_nav unless stated.
P = {
    "GTF": dict(single=8.0, issuer=10.0, sectors=[("Semiconductors", 35.0), ("Software", 40.0), ("Hardware", 25.0)],
                countries=[("United States", 75.0), ("Taiwan", 15.0), ("China", 10.0)], cash=(1.0, 10.0),
                positions=40, turnover=150.0, te=800.0, fx=None, duration=None, hy=None, rating=None,
                deriv=20.0, deriv_nonhedge=None, cpty=15.0, cpty_rating="A-", coal=30.0, tobacco=False,
                illiquid=10.0, liq=80.0, swing=2.0, sleeve=("Private and pre-IPO sleeve", 5.0),
                bench_carve=(3.0, 2.0), ca_scrip_ok=True, frontier=None),
    "EIF": dict(single=5.0, issuer=6.0, sectors=[("Financials", 25.0), ("Utilities", 20.0), ("Real Estate", 15.0)],
                countries=[("United Kingdom", 40.0), ("Germany", 25.0), ("France", 25.0)], cash=(0.0, 5.0),
                positions=50, turnover=60.0, te=400.0, fx=20.0, duration=None, hy=None, rating=None,
                deriv=10.0, deriv_nonhedge="prohibited", cpty=10.0, cpty_rating="A", coal=20.0, tobacco=True,
                illiquid=5.0, liq=90.0, swing=1.5, sleeve=("Small-cap sleeve", 3.0),
                bench_carve=(3.0, 1.5), ca_scrip_ok=True, frontier=None),
    "DGF": dict(single=4.0, issuer=5.0, sectors=[("Technology", 20.0), ("Energy", 15.0), ("Healthcare", 20.0)],
                countries=[("United States", 50.0), ("Japan", 20.0), ("United Kingdom", 20.0)], cash=(2.0, 25.0),
                positions=60, turnover=200.0, te=600.0, fx=30.0, duration=(2.0, 8.0), hy=15.0, rating="B",
                deriv=100.0, deriv_nonhedge=None, cpty=20.0, cpty_rating="A-", coal=25.0, tobacco=False,
                illiquid=15.0, liq=75.0, swing=1.0, sleeve=("Alternatives sleeve", 10.0),
                bench_carve=None, ca_scrip_ok=True, frontier=None),
    "CBF": dict(single=2.0, issuer=3.0, sectors=[("Financials", 25.0), ("Energy", 15.0), ("Utilities", 20.0)],
                countries=[("United States", 50.0), ("United Kingdom", 30.0), ("Italy", 10.0)], cash=(0.0, 10.0),
                positions=100, turnover=100.0, te=150.0, fx=5.0, duration=(4.0, 7.0), hy=10.0, rating="BB-",
                deriv=50.0, deriv_nonhedge="prohibited", cpty=10.0, cpty_rating="A-", coal=30.0, tobacco=False,
                illiquid=10.0, liq=70.0, swing=0.75, sleeve=("Private placement sleeve", 5.0),
                bench_carve=None, ca_scrip_ok=False, frontier=None),
    "EMF": dict(single=6.0, issuer=8.0, sectors=[("Financials", 30.0), ("Technology", 30.0), ("Materials", 20.0)],
                countries=[("China", 30.0), ("India", 25.0), ("Brazil", 15.0)], cash=(0.0, 8.0),
                positions=45, turnover=120.0, te=700.0, fx=None, duration=None, hy=None, rating=None,
                deriv=15.0, deriv_nonhedge=None, cpty=15.0, cpty_rating="BBB+", coal=30.0, tobacco=False,
                illiquid=10.0, liq=70.0, swing=2.5, sleeve=("Frontier markets sleeve", 10.0),
                bench_carve=(4.0, 2.0), ca_scrip_ok=True, frontier=10.0),
}

# Amendments: doc_type -> list of (constraint key, new threshold). Applied to version 2.
AMEND = {
    "GTF": {"guidelines": [("single", 7.0)], "ips": [("cash_max", 12.0)], "liquidity_policy": [("illiquid", 8.0)],
            "esg_policy": [("coal", 25.0)]},
    "EIF": {"guidelines": [("single", 4.5), ("issuer", 5.5)], "derivatives_policy": [("deriv", 12.0)],
            "liquidity_policy": [("swing", 1.0)]},
    "DGF": {"ips": [("duration", (2.0, 7.0)), ("hy", 12.0)], "counterparty_policy": [("cpty", 15.0)],
            "corporate_actions_policy": []},
    "CBF": {"ips": [("duration", (3.5, 7.0))], "guidelines": [("issuer", 3.5)], "esg_policy": [("coal", 20.0)],
            "valuation_policy": []},
    "EMF": {"guidelines": [("single", 5.0)], "ips": [("turnover", 100.0)], "liquidity_policy": [("liq", 75.0)]},
}


def pct(x: float) -> str:
    return f"{x:g}%"


def fund_doc_specs(fund: str, p: dict, version: int, overrides: dict) -> dict[str, list[dict]]:
    """Return doc_type -> list of partial constraint dicts (without ids) for this fund and version."""
    g = dict(p)
    g.update(overrides)
    name = FUND_NAMES[fund]
    docs: dict[str, list[dict]] = {}

    # ---- IPS -------------------------------------------------------------------------------
    ips = [
        dict(type="cash_min", scope={"level": "fund"}, comparator=">=", threshold=g["cash"][0], unit="pct_nav",
             breach_action="block", warn_fraction=0.9, exception=EXC_STD, hard=False,
             canonical_text=f"The Fund shall hold cash and cash equivalents of not less than {pct(g['cash'][0])} of net asset value."),
        dict(type="cash_max", scope={"level": "fund"}, comparator="<=", threshold=g.get("cash_max", g["cash"][1]), unit="pct_nav",
             breach_action="block", warn_fraction=0.9, exception=EXC_STD, hard=False,
             canonical_text=f"Cash and cash equivalents shall not exceed {pct(g.get('cash_max', g['cash'][1]))} of net asset value."),
        dict(type="position_count_min", scope={"level": "fund"}, comparator=">=", threshold=float(g["positions"]), unit="count",
             breach_action="warn", warn_fraction=0.9, exception=EXC_STD, hard=False,
             canonical_text=f"The Fund shall hold a minimum of {g['positions']} distinct positions."),
        dict(type="turnover_max", scope={"level": "fund"}, comparator="<=", threshold=g["turnover"], unit="pct_nav",
             breach_action="warn", warn_fraction=0.9, exception=EXC_STD, hard=False,
             canonical_text=f"Annual portfolio turnover shall not exceed {pct(g['turnover'])} of average net assets."),
        dict(type="tracking_error_max", scope={"level": "fund"}, comparator="<=", threshold=g["te"], unit="bps",
             breach_action="block", warn_fraction=0.9, exception=EXC_RISK, hard=False,
             canonical_text=f"Ex-ante tracking error against the benchmark shall not exceed {g['te']:g} basis points."),
        dict(type="sector_max", scope={"level": "sector", "target": g["sectors"][0][0]}, comparator="<=",
             threshold=g["sectors"][0][1], unit="pct_nav", breach_action="block", warn_fraction=0.9, exception=EXC_STD, hard=False,
             canonical_text=f"Exposure to the {g['sectors'][0][0]} sector shall not exceed {pct(g['sectors'][0][1])} of net asset value."),
        dict(type="country_max", scope={"level": "country", "target": g["countries"][0][0]}, comparator="<=",
             threshold=g["countries"][0][1], unit="pct_nav", breach_action="block", warn_fraction=0.9, exception=EXC_STD, hard=False,
             canonical_text=f"Exposure to issuers domiciled in {g['countries'][0][0]} shall not exceed {pct(g['countries'][0][1])} of net asset value."),
    ]
    if g["fx"] is not None:
        ips.append(dict(type="unhedged_fx_max", scope={"level": "fund"}, comparator="<=", threshold=g["fx"], unit="pct_nav",
                        breach_action="block", warn_fraction=0.9, exception=EXC_RISK, hard=False,
                        canonical_text=f"Unhedged non-base-currency exposure shall not exceed {pct(g['fx'])} of net asset value."))
    if g["duration"] is not None:
        lo, hi = g["duration"]
        ips.append(dict(type="duration_band", scope={"level": "fund"}, comparator="between", threshold=[lo, hi], unit="years",
                        breach_action="block", warn_fraction=0.9, exception=EXC_RISK, hard=False,
                        canonical_text=f"Portfolio modified duration shall be maintained between {lo:g} and {hi:g} years."))
    if g["hy"] is not None:
        ips.append(dict(type="hy_max", scope={"level": "fund"}, comparator="<=", threshold=g["hy"], unit="pct_nav",
                        breach_action="block", warn_fraction=0.9, exception=EXC_STD, hard=False,
                        canonical_text=f"Holdings rated below investment grade shall not exceed {pct(g['hy'])} of net asset value."))
    if g["rating"] is not None:
        ips.append(dict(type="credit_min_rating", scope={"level": "fund"}, comparator=">=", threshold=g["rating"], unit="rating",
                        breach_action="block", warn_fraction=None, exception=EXC_STD, hard=False,
                        canonical_text=f"No security rated below {g['rating']} (or equivalent) may be purchased."))
    ips.append(dict(type="cash_max", scope={"level": "fund"}, comparator="<=", threshold=3.0, unit="pct_nav",
                    breach_action="warn", warn_fraction=None, exception=EXC_STD, hard=False, distractor=True,
                    canonical_text="In normal market conditions the Manager expects to hold cash of around 3% of net asset value."))
    ips.append(dict(type="turnover_max", scope={"level": "fund"}, comparator="<=", threshold=g["turnover"] * 0.6, unit="pct_nav",
                    breach_action="warn", warn_fraction=None, exception=EXC_STD, hard=False, distractor=True,
                    canonical_text=f"Historically the Fund's turnover has averaged approximately {pct(g['turnover'] * 0.6)} per annum."))
    docs["ips"] = ips

    # ---- Guidelines --------------------------------------------------------------------------
    single = g.get("single_max", g["single"])
    gl = [
        dict(type="single_name_max", scope={"level": "fund"}, comparator="<=", threshold=single, unit="pct_nav",
             breach_action="block", warn_fraction=0.9, exception=EXC_STD, hard=False,
             canonical_text=f"No single security shall exceed {pct(single)} of net asset value."),
        dict(type="issuer_max", scope={"level": "fund"}, comparator="<=", threshold=g.get("issuer_max", g["issuer"]), unit="pct_nav",
             breach_action="block", warn_fraction=0.9, exception=EXC_STD, hard=False,
             canonical_text=f"Aggregate exposure to any single issuer, including all securities of that issuer, shall not exceed {pct(g.get('issuer_max', g['issuer']))} of net asset value."),
        dict(type="sector_max", scope={"level": "sector", "target": g["sectors"][1][0]}, comparator="<=", threshold=g["sectors"][1][1],
             unit="pct_nav", breach_action="block", warn_fraction=0.9, exception=EXC_STD, hard=False,
             canonical_text=f"Exposure to the {g['sectors'][1][0]} sector shall not exceed {pct(g['sectors'][1][1])} of net asset value."),
        dict(type="sector_max", scope={"level": "sector", "target": g["sectors"][2][0]}, comparator="<=", threshold=g["sectors"][2][1],
             unit="pct_nav", breach_action="block", warn_fraction=0.9, exception=EXC_STD, hard=False,
             canonical_text=f"Exposure to the {g['sectors'][2][0]} sector shall not exceed {pct(g['sectors'][2][1])} of net asset value."),
        dict(type="country_max", scope={"level": "country", "target": g["countries"][1][0]}, comparator="<=", threshold=g["countries"][1][1],
             unit="pct_nav", breach_action="block", warn_fraction=0.9, exception=EXC_STD, hard=False,
             canonical_text=f"Exposure to issuers domiciled in {g['countries'][1][0]} shall not exceed {pct(g['countries'][1][1])} of net asset value."),
        dict(type="country_max", scope={"level": "country", "target": g["countries"][2][0]}, comparator="<=", threshold=g["countries"][2][1],
             unit="pct_nav", breach_action="block", warn_fraction=0.9, exception=EXC_STD, hard=False,
             canonical_text=f"Exposure to issuers domiciled in {g['countries'][2][0]} shall not exceed {pct(g['countries'][2][1])} of net asset value."),
        dict(type="single_name_max", scope={"level": "sleeve", "target": g["sleeve"][0]}, comparator="<=", threshold=g["sleeve"][1],
             unit="pct_nav", breach_action="block", warn_fraction=0.9, exception=EXC_STD, hard=False,
             canonical_text=f"Within the {g['sleeve'][0]}, no single security shall exceed {pct(g['sleeve'][1])} of net asset value."),
        dict(type="restricted_list", scope={"level": "fund"}, comparator="prohibited", threshold="Restricted List", unit="none",
             breach_action="hard_block", warn_fraction=None, exception=EXC_NONE, hard=True,
             canonical_text="No security of an issuer appearing on the Firm's Restricted List may be purchased or added to under any circumstances; this restriction cannot be waived by the Manager, the Chief Investment Officer or Compliance."),
    ]
    if g["bench_carve"]:
        bw, plus = g["bench_carve"]
        gl[0]["carve_out"] = {"condition_field": "benchmark_weight", "condition_op": ">", "condition_value": bw,
                              "alt_threshold": f"benchmark_weight+{plus:g}",
                              "alt_text": f"unless the security represents more than {pct(bw)} of the benchmark, in which case the limit is the benchmark weight plus {plus:g} percentage points"}
        gl[0]["canonical_text"] = f"No single security shall exceed {pct(single)} of net asset value, {gl[0]['carve_out']['alt_text']}."
    if g["frontier"] is not None:
        gl.append(dict(type="country_max", scope={"level": "country", "target": "Frontier markets"}, comparator="<=", threshold=g["frontier"],
                       unit="pct_nav", breach_action="block", warn_fraction=0.9, exception=EXC_STD, hard=False,
                       canonical_text=f"Aggregate exposure to frontier markets shall not exceed {pct(g['frontier'])} of net asset value."))
    gl.append(dict(type="single_name_max", scope={"level": "fund"}, comparator="<=", threshold=single * 0.5, unit="pct_nav",
                   breach_action="warn", warn_fraction=None, exception=EXC_STD, hard=False, distractor=True,
                   canonical_text=f"The Manager's typical initial position size is approximately {pct(single * 0.5)} of net asset value."))
    docs["guidelines"] = gl

    # ---- Derivatives policy ------------------------------------------------------------------
    dv = [
        dict(type="derivatives_notional_max", scope={"level": "fund"}, comparator="<=", threshold=g.get("deriv_max", g["deriv"]), unit="pct_nav",
             breach_action="block", warn_fraction=0.9, exception=EXC_RISK, hard=False,
             canonical_text=f"Gross notional exposure through derivatives shall not exceed {pct(g.get('deriv_max', g['deriv']))} of net asset value."),
        dict(type="counterparty_max", scope={"level": "issuer", "target": "any single derivatives counterparty"}, comparator="<=",
             threshold=g["cpty"], unit="pct_nav", breach_action="block", warn_fraction=0.9, exception=EXC_RISK, hard=False,
             canonical_text=f"Mark-to-market exposure to any single derivatives counterparty shall not exceed {pct(g['cpty'])} of net asset value."),
        dict(type="credit_min_rating", scope={"level": "issuer", "target": "derivatives counterparty"}, comparator=">=", threshold=g["cpty_rating"],
             unit="rating", breach_action="block", warn_fraction=None, exception=EXC_RISK, hard=False,
             canonical_text=f"Derivatives may only be transacted with counterparties rated {g['cpty_rating']} or better by at least one recognised rating agency."),
        dict(type="counterparty_max", scope={"level": "sleeve", "target": "uncollateralised derivatives exposure"}, comparator="<=",
             threshold=5.0, unit="pct_nav", breach_action="block", warn_fraction=0.9, exception=EXC_RISK, hard=False,
             canonical_text="Uncollateralised derivatives exposure shall not exceed 5% of net asset value."),
    ]
    if g["deriv_nonhedge"] == "prohibited":
        dv.append(dict(type="derivatives_notional_max", scope={"level": "sleeve", "target": "non-hedging derivatives"}, comparator="prohibited",
                       threshold="non-hedging derivatives", unit="none", breach_action="block", warn_fraction=None, exception=EXC_RISK, hard=False,
                       canonical_text="Derivatives may be used for hedging purposes only; derivatives that increase market exposure are prohibited."))
    dv.append(dict(type="derivatives_notional_max", scope={"level": "fund"}, comparator="<=", threshold=g["deriv"] * 0.4, unit="pct_nav",
                   breach_action="warn", warn_fraction=None, exception=EXC_RISK, hard=False, distractor=True,
                   canonical_text=f"Over the last three years gross notional derivatives exposure has typically been around {pct(g['deriv'] * 0.4)} of net asset value."))
    docs["derivatives_policy"] = dv

    # ---- ESG policy --------------------------------------------------------------------------
    coal = g.get("coal_max", g["coal"])
    es = [
        dict(type="esg_exclusion", scope={"level": "issuer", "target": "controversial weapons"}, comparator="prohibited",
             threshold="controversial weapons", unit="none", breach_action="hard_block", warn_fraction=None, exception=EXC_NONE, hard=True,
             canonical_text="Issuers involved in the production of controversial weapons (cluster munitions, anti-personnel mines, biological and chemical weapons) are excluded absolutely; no exception may be granted by any person."),
        dict(type="esg_exclusion", scope={"level": "issuer", "target": "thermal coal"}, comparator="prohibited",
             threshold=coal, unit="pct_nav", breach_action="block", warn_fraction=None, exception=EXC_STD, hard=False,
             canonical_text=f"Issuers deriving more than {pct(coal)} of revenue from thermal coal extraction or thermal coal power generation are excluded."),
        dict(type="esg_exclusion", scope={"level": "issuer", "target": "UN Global Compact violators"}, comparator="prohibited",
             threshold="UN Global Compact violators", unit="none", breach_action="block", warn_fraction=None, exception=EXC_STD, hard=False,
             canonical_text="Issuers assessed as being in breach of the UN Global Compact principles are excluded."),
    ]
    if g["tobacco"]:
        es.append(dict(type="esg_exclusion", scope={"level": "issuer", "target": "tobacco"}, comparator="prohibited", threshold="tobacco",
                       unit="none", breach_action="block", warn_fraction=None, exception=EXC_STD, hard=False,
                       canonical_text="Tobacco producers are excluded from the Fund."))
    if fund == "CBF":
        es[1]["carve_out"] = {"condition_field": "certified_green_bond", "condition_op": "is_true", "condition_value": True,
                              "alt_threshold": None,
                              "alt_text": "unless the security is a certified green bond whose proceeds are ring-fenced for transition projects"}
        es[1]["canonical_text"] = f"Issuers deriving more than {pct(coal)} of revenue from thermal coal are excluded, {es[1]['carve_out']['alt_text']}."
    es.append(dict(type="esg_exclusion", scope={"level": "fund", "target": "carbon intensity"}, comparator="<=", threshold=30.0, unit="pct_nav",
                   breach_action="warn", warn_fraction=None, exception=EXC_STD, hard=False, distractor=True,
                   canonical_text="The Manager aims to reduce the portfolio's weighted average carbon intensity by 30% relative to the benchmark over time."))
    docs["esg_policy"] = es

    # ---- Liquidity policy ----------------------------------------------------------------------
    lq = [
        dict(type="illiquid_max", scope={"level": "fund"}, comparator="<=", threshold=g.get("illiquid_max", g["illiquid"]), unit="pct_nav",
             breach_action="block", warn_fraction=0.9, exception=EXC_RISK, hard=False,
             canonical_text=f"Holdings classified as illiquid shall not exceed {pct(g.get('illiquid_max', g['illiquid']))} of net asset value."),
        dict(type="liquidity_min_daily", scope={"level": "fund"}, comparator=">=", threshold=g.get("liq_min", g["liq"]), unit="pct_nav",
             breach_action="block", warn_fraction=0.9, exception=EXC_RISK, hard=False,
             canonical_text=f"At least {pct(g.get('liq_min', g['liq']))} of net asset value shall be realisable within five business days under normal market conditions."),
        dict(type="swing_threshold", scope={"level": "fund"}, comparator="required", threshold=g.get("swing_thr", g["swing"]), unit="pct_nav",
             breach_action="block", warn_fraction=None, exception=EXC_RISK, hard=False,
             canonical_text=f"Swing pricing shall be applied on any dealing day on which net flows exceed {pct(g.get('swing_thr', g['swing']))} of net asset value."),
        dict(type="liquidity_min_daily", scope={"level": "issuer", "target": "days to liquidate"}, comparator="<=", threshold=5.0, unit="days",
             breach_action="warn", warn_fraction=0.8, exception=EXC_RISK, hard=False,
             canonical_text="No single position shall require more than 5 business days to liquidate at 25% of average daily volume."),
        dict(type="illiquid_max", scope={"level": "fund"}, comparator="<=", threshold=g["illiquid"] * 0.3, unit="pct_nav",
             breach_action="warn", warn_fraction=None, exception=EXC_RISK, hard=False, distractor=True,
             canonical_text=f"At the last review illiquid holdings represented approximately {pct(g['illiquid'] * 0.3)} of net asset value."),
    ]
    docs["liquidity_policy"] = lq

    # ---- Valuation policy ----------------------------------------------------------------------
    vp = [
        dict(type="valuation_lot_rule", scope={"level": "fund", "target": "odd lot"}, comparator="required", threshold="odd_lot_pricing", unit="none",
             breach_action="block", warn_fraction=None, exception=EXC_VAL, hard=False,
             canonical_text="Positions held in odd lots shall be valued using odd-lot prices; institutional round-lot prices shall not be applied to odd-lot positions."),
        dict(type="valuation_lot_rule", scope={"level": "fund", "target": "level 3"}, comparator="required", threshold="committee_approval", unit="none",
             breach_action="block", warn_fraction=None, exception=EXC_VAL, hard=False,
             canonical_text="Any mark applied to a Level 3 asset requires prior approval of the Valuation Committee."),
        dict(type="valuation_lot_rule", scope={"level": "fund", "target": "stale price"}, comparator="required", threshold=5.0, unit="days",
             breach_action="block", warn_fraction=None, exception=EXC_VAL, hard=False,
             canonical_text="A price that has not been updated for more than 5 business days is deemed stale and must be referred to the Valuation Committee before use."),
        dict(type="valuation_lot_rule", scope={"level": "fund", "target": "review frequency"}, comparator="required", threshold=90.0, unit="days",
             breach_action="warn", warn_fraction=None, exception=EXC_VAL, hard=False, distractor=True,
             canonical_text="The Valuation Committee reviews its pricing sources approximately every 90 days."),
    ]
    docs["valuation_policy"] = vp

    # ---- Counterparty policy -------------------------------------------------------------------
    cp = [
        dict(type="counterparty_max", scope={"level": "issuer", "target": "any single securities lending counterparty"}, comparator="<=",
             threshold=g.get("cpty_max", g["cpty"]), unit="pct_nav", breach_action="block", warn_fraction=0.9, exception=EXC_RISK, hard=False,
             canonical_text=f"Exposure to any single securities lending or repo counterparty shall not exceed {pct(g.get('cpty_max', g['cpty']))} of net asset value."),
        dict(type="counterparty_max", scope={"level": "issuer", "target": "affiliated entity"}, comparator="prohibited", threshold="affiliated entity",
             unit="none", breach_action="hard_block", warn_fraction=None, exception=EXC_NONE, hard=True,
             canonical_text="No transaction may be entered into with an entity affiliated with the Manager; this conflict-of-interest prohibition cannot be overridden by any individual or committee."),
        dict(type="credit_min_rating", scope={"level": "issuer", "target": "deposit bank"}, comparator=">=", threshold="A-", unit="rating",
             breach_action="block", warn_fraction=None, exception=EXC_RISK, hard=False,
             canonical_text="Cash deposits may only be placed with banks rated A- or better."),
        dict(type="counterparty_max", scope={"level": "issuer", "target": "any single executing broker"}, comparator="<=", threshold=25.0, unit="pct_nav",
             breach_action="warn", warn_fraction=0.9, exception=EXC_RISK, hard=False,
             canonical_text="No single executing broker shall account for more than 25% of the Fund's annual traded value."),
        dict(type="counterparty_max", scope={"level": "issuer", "target": "any single securities lending counterparty"}, comparator="<=",
             threshold=g["cpty"] * 0.5, unit="pct_nav", breach_action="warn", warn_fraction=None, exception=EXC_RISK, hard=False, distractor=True,
             canonical_text=f"Securities lending exposure to the largest counterparty is currently about {pct(g['cpty'] * 0.5)} of net asset value."),
    ]
    docs["counterparty_policy"] = cp

    # ---- Corporate actions policy ----------------------------------------------------------------
    ca = [
        dict(type="ca_election_default", scope={"level": "fund", "target": "scrip dividend"}, comparator="required", threshold="cash", unit="none",
             breach_action="block", warn_fraction=None, exception=EXC_STD, hard=False,
             canonical_text=("Scrip dividend alternatives shall be taken in cash by default; a scrip election requires a documented rationale from the portfolio manager"
                             + (" and is prohibited where the post-election position would exceed the single security limit in the Investment Guidelines." if g["ca_scrip_ok"]
                                else " and is not permitted for this Fund.")) ),
        dict(type="ca_election_default", scope={"level": "fund", "target": "rights issue"}, comparator="required", threshold="take_up", unit="none",
             breach_action="block", warn_fraction=None, exception=EXC_STD, hard=False,
             canonical_text="Rights issues shall be taken up by default; a decision to let rights lapse or to sell nil-paid rights requires a documented rationale from the portfolio manager."),
        dict(type="ca_election_default", scope={"level": "fund", "target": "tender offer"}, comparator="required", threshold="decline", unit="none",
             breach_action="block", warn_fraction=None, exception=EXC_STD, hard=False,
             canonical_text="Tender offers shall be declined by default; tendering requires approval of the Chief Investment Officer."),
        dict(type="ca_election_default", scope={"level": "fund", "target": "election deadline"}, comparator="required", threshold=2.0, unit="days",
             breach_action="warn", warn_fraction=None, exception=EXC_STD, hard=False,
             canonical_text="Elections shall be instructed to the custodian no later than 2 business days before the custodian deadline."),
        dict(type="ca_election_default", scope={"level": "fund", "target": "scrip dividend"}, comparator="required", threshold="cash", unit="none",
             breach_action="warn", warn_fraction=None, exception=EXC_STD, hard=False, distractor=True,
             canonical_text="In recent years the majority of scrip alternatives offered to the Fund have been taken in cash."),
    ]
    docs["corporate_actions_policy"] = ca
    return docs


def apply_amendments(fund: str, doc_type: str) -> dict:
    ov: dict = {}
    for key, val in AMEND.get(fund, {}).get(doc_type, []):
        if key == "single": ov["single_max"] = val
        elif key == "issuer": ov["issuer_max"] = val
        elif key == "cash_max": ov["cash_max"] = val
        elif key == "illiquid": ov["illiquid_max"] = val
        elif key == "coal": ov["coal_max"] = val
        elif key == "deriv": ov["deriv_max"] = val
        elif key == "swing": ov["swing_thr"] = val
        elif key == "duration": ov["duration"] = val
        elif key == "hy": ov["hy"] = val
        elif key == "cpty": ov["cpty_max"] = val
        elif key == "turnover": ov["turnover"] = val
        elif key == "liq": ov["liq_min"] = val
    return ov


DOC_TITLES = {
    "ips": "Investment Policy Statement",
    "guidelines": "Investment Guidelines and Restrictions",
    "derivatives_policy": "Derivatives Usage Policy",
    "esg_policy": "Responsible Investment Exclusions Policy",
    "liquidity_policy": "Liquidity Risk Management Policy",
    "valuation_policy": "Valuation and Pricing Policy",
    "counterparty_policy": "Counterparty and Broker Policy",
    "corporate_actions_policy": "Corporate Actions Election Policy",
}


def generate(seed: int = 0) -> tuple[list[dict], list[dict]]:
    rng = random.Random(seed)
    constraints: list[dict] = []
    documents: list[dict] = []
    for fund in FUNDS:
        p = P[fund]
        for doc_type in DOC_TITLES:
            doc_id = f"{fund}-{doc_type}"
            amended = doc_type in AMEND.get(fund, {})
            versions = [(1, V1_DATE, {})]
            if amended:
                versions.append((2, V2_DATE, apply_amendments(fund, doc_type)))
            doc = {"doc_id": doc_id, "fund": fund, "doc_type": doc_type,
                   "title": f"{FUND_NAMES[fund]}: {DOC_TITLES[doc_type]}", "versions": [], "renderings": []}
            for version, eff, ov in versions:
                specs = fund_doc_specs(fund, p, version, ov)[doc_type]
                ids = []
                for i, c in enumerate(specs, start=1):
                    cid = f"{fund}-{doc_type}-v{version}-C{i:02d}"
                    row = {"id": cid, "fund": fund, "doc_id": doc_id, "version": version,
                           "effective_from": eff, "effective_to": None}
                    row.update(c)
                    row.setdefault("distractor", False)
                    validate_constraint(row)
                    constraints.append(row)
                    ids.append(cid)
                note = None
                if version == 2:
                    changed = [k for k, _ in AMEND[fund][doc_type]]
                    note = "Amendment effective " + eff + " changing: " + ", ".join(changed) if changed else "Restatement without threshold changes"
                doc["versions"].append({"version": version, "effective_from": eff,
                                        "superseded_by": 2 if (version == 1 and amended) else None,
                                        "constraint_ids": ids, **({"amendment_note": note} if note else {})})
            # mark v1 constraints superseded where v2 exists
            if amended:
                for c in constraints:
                    if c["doc_id"] == doc_id and c["version"] == 1:
                        c["effective_to"] = V2_DATE
            documents.append(doc)
    rng.shuffle(constraints)  # order on disk carries no information
    constraints.sort(key=lambda c: c["id"])
    return constraints, documents


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/specs")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    cons, docs = generate(a.seed)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    (out / "constraints.json").write_text(json.dumps(cons, indent=1))
    (out / "documents.json").write_text(json.dumps(docs, indent=1))
    binding = sum(1 for c in cons if not c["distractor"])
    hard = sum(1 for c in cons if c["hard"])
    carve = sum(1 for c in cons if "carve_out" in c)
    v2 = sum(1 for c in cons if c["version"] == 2)
    print(f"constraints={len(cons)} binding={binding} distractors={len(cons)-binding} hard={hard} carve_outs={carve} v2_rows={v2} documents={len(docs)} versions={sum(len(d['versions']) for d in docs)}")


if __name__ == "__main__":
    main()
