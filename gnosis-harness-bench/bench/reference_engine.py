"""Deterministic reference policy engine: computes gold verdicts from structured specs.

Implements bench/policy_semantics.md exactly. This is the ground truth for the verdict task.
It is deliberately simple and fully enumerable so that every gold label can be audited by hand.
"""
from __future__ import annotations

from dataclasses import dataclass, field

SEVERITY = {"pass": 0, "warn": 1, "breach": 2, "hard_block": 3}
APPROVER_ORDER = ["PM", "CIO", "Compliance", "Risk", "ValuationCommittee"]
RATING_ORDER = ["AAA", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-", "BB+", "BB", "BB-",
                "B+", "B", "B-", "CCC+", "CCC", "CCC-", "CC", "C", "D", "NR"]
IG_FLOOR = "BBB-"
NA = object()          # constraint not applicable to this decision
MISSING = object()     # required input absent


def rating_worse_than(r: str, floor: str) -> bool:
    return RATING_ORDER.index(r) > RATING_ORDER.index(floor)


def version_in_force(doc: dict, as_of: str) -> int | None:
    vs = [v for v in doc["versions"] if v["effective_from"] <= as_of]
    return max(v["version"] for v in vs) if vs else None


@dataclass
class State:
    ex: dict[str, float]
    flags: dict[str, object]
    changed: set[str] = field(default_factory=set)
    missing: set[str] = field(default_factory=set)


def post_trade(portfolio: dict, proposal: dict) -> State:
    """Apply the proposal to the portfolio exposures and collect flags for non-numeric rules."""
    ex = dict(portfolio["exposures"])
    ex.setdefault("holdings_count", float(portfolio.get("holdings_count", 0)))
    f = proposal["fields"]
    dt = proposal["decision_type"]
    st = State(ex=ex, flags=dict(f))

    def need(*keys: str) -> bool:
        ok = True
        for k in keys:
            if k not in f or f[k] is None:
                st.missing.add(k); ok = False
        return ok

    def position_change(current_key: str, target_key: str) -> None:
        if not need("ticker", target_key):
            st.changed.update({"single_name", "cash"})
            return
        cur = float(f.get(current_key, ex.get(f"single_name:{f['ticker']}", 0.0)))
        tgt = float(f[target_key])
        delta = tgt - cur
        ex[f"single_name:{f['ticker']}"] = tgt
        st.changed.add("single_name")
        if f.get("sleeve"):
            ex[f"sleeve:{f['sleeve']}:{f['ticker']}"] = tgt; st.changed.add("sleeve")
        if f.get("issuer"):
            ex[f"issuer:{f['issuer']}"] = ex.get(f"issuer:{f['issuer']}", cur) + delta; st.changed.add("issuer")
        if f.get("sector"):
            ex[f"sector:{f['sector']}"] = ex.get(f"sector:{f['sector']}", 0.0) + delta; st.changed.add("sector")
        if f.get("country"):
            ex[f"country:{f['country']}"] = ex.get(f"country:{f['country']}", 0.0) + delta; st.changed.add("country")
        if f.get("country_bucket"):
            ex[f"country:{f['country_bucket']}"] = ex.get(f"country:{f['country_bucket']}", 0.0) + delta; st.changed.add("country")
        if f.get("funded_from_cash", True):
            ex["cash"] = ex.get("cash", 0.0) - delta; st.changed.add("cash")
        if f.get("illiquid"):
            ex["illiquid"] = ex.get("illiquid", 0.0) + delta; ex["liquid_5d"] = ex.get("liquid_5d", 100.0) - delta
            st.changed.update({"illiquid", "liquid_5d"})
        if f.get("rating") and rating_worse_than(f["rating"], IG_FLOOR):
            ex["hy"] = ex.get("hy", 0.0) + delta; st.changed.add("hy")
        if delta > 0:
            st.flags["is_purchase"] = True

    if dt in ("single_name_overweight", "single_name_new_position", "exit_sell"):
        position_change("current_weight", "target_weight")
        if dt == "single_name_new_position":
            ex["holdings_count"] += 1; st.changed.add("holdings_count")
        if dt == "exit_sell":
            ex["holdings_count"] -= 1; st.changed.add("holdings_count")
    elif dt == "sector_tilt":
        if need("sector", "target_weight"):
            cur = ex.get(f"sector:{f['sector']}", 0.0); ex[f"sector:{f['sector']}"] = float(f["target_weight"]); st.changed.add("sector")
            if f.get("funded_from_cash", True):
                ex["cash"] = ex.get("cash", 0.0) - (float(f["target_weight"]) - cur); st.changed.add("cash")
    elif dt == "country_tilt":
        if need("country", "target_weight"):
            cur = ex.get(f"country:{f['country']}", 0.0); ex[f"country:{f['country']}"] = float(f["target_weight"]); st.changed.add("country")
            if f.get("funded_from_cash", True):
                ex["cash"] = ex.get("cash", 0.0) - (float(f["target_weight"]) - cur); st.changed.add("cash")
    elif dt == "cash_level_change":
        if need("target_cash"):
            ex["cash"] = float(f["target_cash"])
        st.changed.update({"cash", "flows"})
    elif dt == "duration_extension":
        if need("target_duration"):
            ex["duration"] = float(f["target_duration"]); st.changed.add("duration")
    elif dt == "credit_quality_shift":
        if need("hy_target"):
            ex["hy"] = float(f["hy_target"]); st.changed.add("hy")
        st.changed.add("rating")
    elif dt == "fx_hedge_ratio_change":
        if need("unhedged_target"):
            ex["unhedged_fx"] = float(f["unhedged_target"]); st.changed.add("unhedged_fx")
    elif dt == "derivatives_overlay":
        if need("notional_target"):
            ex["derivatives_notional"] = float(f["notional_target"]); st.changed.add("derivatives_notional")
        if f.get("counterparty") is not None and f.get("counterparty_target") is not None:
            ex[f"counterparty:{f['counterparty']}"] = float(f["counterparty_target"])
        st.changed.update({"counterparty", "derivatives_purpose"})
    elif dt == "corporate_action_election":
        if need("event_type", "election"):
            pass
        if f.get("post_election_weight") is not None and f.get("ticker"):
            ex[f"single_name:{f['ticker']}"] = float(f["post_election_weight"]); st.changed.add("single_name")
            if float(f["post_election_weight"]) > float(f.get("current_weight", 0.0)):
                st.flags["is_purchase"] = True
        st.changed.add("corporate_action")
    elif dt == "guideline_exception_request":
        need("constraint_type", "requested_exposure", "duration_days")
        st.changed.add("exception_request")
    elif dt == "valuation_mark_override":
        need("lot_size", "level", "days_stale", "mark_source")
        st.changed.add("valuation")
    return st


def effective_threshold(c: dict, st: State):
    thr = c["threshold"]
    co = c.get("carve_out")
    if not co:
        return thr
    val = st.flags.get(co["condition_field"])
    if val is None:
        return thr
    op, cv = co["condition_op"], co["condition_value"]
    hit = {">": lambda a, b: a > b, ">=": lambda a, b: a >= b, "==": lambda a, b: a == b,
           "<": lambda a, b: a < b, "<=": lambda a, b: a <= b, "is_true": lambda a, b: bool(a) is True}[op](val, cv)
    if not hit:
        return thr
    alt = co["alt_threshold"]
    if isinstance(alt, str) and alt.startswith("benchmark_weight+"):
        return float(st.flags.get("benchmark_weight", 0.0)) + float(alt.split("+")[1])
    return alt


def exposure_value(c: dict, st: State):
    """Return the post-trade value a constraint is tested against, NA if not applicable, MISSING if an input is absent."""
    t, sc, f, ex = c["type"], c["scope"], st.flags, st.ex
    tgt = sc.get("target")
    dt = f.get("decision_type")
    if f.get("_dt") == "guideline_exception_request" or dt == "guideline_exception_request":
        pass
    if "exception_request" in st.changed:
        if f.get("constraint_type") == t and (tgt is None or f.get("scope_target") == tgt) and sc["level"] == f.get("scope_level", sc["level"]):
            return MISSING if f.get("requested_exposure") is None else float(f["requested_exposure"])
        return NA
    if t == "single_name_max":
        if "single_name" not in st.changed: return NA
        if sc["level"] == "sleeve":
            if f.get("sleeve") != tgt: return NA
            return MISSING if "target_weight" in st.missing else ex.get(f"sleeve:{tgt}:{f.get('ticker')}", NA)
        return MISSING if "target_weight" in st.missing else ex.get(f"single_name:{f.get('ticker')}", NA)
    if t == "issuer_max":
        return ex.get(f"issuer:{f['issuer']}", NA) if "issuer" in st.changed and f.get("issuer") else NA
    if t == "sector_max":
        return ex.get(f"sector:{tgt}", NA) if "sector" in st.changed and f.get("sector") == tgt else NA
    if t == "country_max":
        if "country" not in st.changed: return NA
        if f.get("country") == tgt or f.get("country_bucket") == tgt:
            return ex.get(f"country:{tgt}", NA)
        return NA
    if t in ("cash_min", "cash_max"):
        if "cash" not in st.changed: return NA
        return MISSING if ("target_cash" in st.missing or "target_weight" in st.missing) else ex.get("cash", NA)
    if t == "position_count_min":
        return ex.get("holdings_count", NA) if "holdings_count" in st.changed else NA
    if t == "turnover_max":
        return float(f["turnover_post"]) if f.get("turnover_post") is not None else NA
    if t == "tracking_error_max":
        return float(f["te_post_bps"]) if f.get("te_post_bps") is not None else NA
    if t == "unhedged_fx_max":
        if "unhedged_fx" not in st.changed and "unhedged_target" not in st.missing: return NA
        return MISSING if "unhedged_target" in st.missing else ex.get("unhedged_fx", NA)
    if t == "duration_band":
        if "duration" not in st.changed and "target_duration" not in st.missing: return NA
        return MISSING if "target_duration" in st.missing else ex.get("duration", NA)
    if t == "hy_max":
        if "hy" not in st.changed and "hy_target" not in st.missing: return NA
        return MISSING if "hy_target" in st.missing else ex.get("hy", NA)
    if t == "credit_min_rating":
        if sc["level"] == "fund":
            if "rating" in st.changed and f.get("min_rating_added"): return f["min_rating_added"]
            if f.get("rating") and f.get("is_purchase"): return f["rating"]
            return NA
        if tgt == "derivatives counterparty":
            return f["counterparty_rating"] if "counterparty" in st.changed and f.get("counterparty_rating") else NA
        return NA
    if t == "esg_exclusion":
        if not f.get("is_purchase"): return NA
        inv = set(f.get("esg_involvement") or [])
        if tgt == "thermal coal":
            return float(f["thermal_coal_revenue_pct"]) if f.get("thermal_coal_revenue_pct") is not None else NA
        return (tgt in inv)
    if t == "restricted_list":
        return bool(f.get("restricted")) if f.get("is_purchase") else NA
    if t == "derivatives_notional_max":
        if "derivatives_notional" not in st.changed and "notional_target" not in st.missing: return NA
        if c["comparator"] == "prohibited":
            return f.get("purpose") == "non_hedging"
        return MISSING if "notional_target" in st.missing else ex.get("derivatives_notional", NA)
    if t == "counterparty_max":
        if "counterparty" not in st.changed: return NA
        if tgt == "any single derivatives counterparty":
            return ex.get(f"counterparty:{f.get('counterparty')}", NA) if f.get("counterparty") else NA
        if tgt == "uncollateralised derivatives exposure":
            return float(f["uncollateralised_exposure"]) if f.get("uncollateralised_exposure") is not None else NA
        if tgt == "affiliated entity":
            return bool(f.get("affiliated"))
        return NA
    if t == "illiquid_max":
        return ex.get("illiquid", NA) if "illiquid" in st.changed else NA
    if t == "liquidity_min_daily":
        if tgt == "days to liquidate":
            return float(f["days_to_liquidate"]) if f.get("days_to_liquidate") is not None else NA
        return ex.get("liquid_5d", NA) if "liquid_5d" in st.changed else NA
    if t == "swing_threshold":
        if "flows" not in st.changed: return NA
        if f.get("net_flow_pct") is None: return NA
        return {"net_flow_pct": abs(float(f["net_flow_pct"])), "swing_applied": bool(f.get("swing_applied"))}
    if t == "valuation_lot_rule":
        if "valuation" not in st.changed: return NA
        if st.missing: return MISSING
        return dict(f)
    if t == "ca_election_default":
        if "corporate_action" not in st.changed: return NA
        if st.missing: return MISSING
        return dict(f)
    return NA


def evaluate_one(c: dict, val, st: State, single_limit: float | None) -> tuple[str, str]:
    """Return (verdict, reason). reason in {"ok","warn_band","soft_exceeded","exceeded","missing_input"}."""
    if val is MISSING:
        return "warn", "missing_input"
    thr = effective_threshold(c, st)
    comp, w = c["comparator"], c.get("warn_fraction")
    exceeded = False; in_band = False
    if comp == "<=":
        v = float(val); L = float(thr)
        exceeded = v > L + 1e-9
        in_band = (not exceeded) and w is not None and v >= w * L - 1e-9
    elif comp == ">=":
        if c["unit"] == "rating":
            exceeded = rating_worse_than(str(val), str(thr))
        else:
            v = float(val); F = float(thr)
            exceeded = v < F - 1e-9
            in_band = (not exceeded) and w is not None and v < F * (2 - w) - 1e-9
    elif comp == "between":
        v = float(val); lo, hi = float(thr[0]), float(thr[1])
        exceeded = v < lo - 1e-9 or v > hi + 1e-9
        if not exceeded and w is not None:
            edge = (1 - w) * (hi - lo)
            in_band = v < lo + edge or v > hi - edge
    elif comp == "prohibited":
        if c["type"] == "esg_exclusion" and c["scope"].get("target") == "thermal coal":
            exceeded = thr is not None and float(val) > float(thr)
        else:
            exceeded = bool(val)
    elif comp == "required":
        f = val if isinstance(val, dict) else {}
        tgt = c["scope"].get("target")
        if c["type"] == "swing_threshold":
            exceeded = f["net_flow_pct"] > float(thr) and not f["swing_applied"]
        elif c["type"] == "valuation_lot_rule":
            if tgt == "odd lot":
                exceeded = f.get("lot_size") == "odd" and f.get("mark_source") == "institutional_lot"
            elif tgt == "level 3":
                exceeded = int(f.get("level", 1)) == 3 and not f.get("committee_approved")
            elif tgt == "stale price":
                exceeded = float(f.get("days_stale", 0)) > float(thr) and not f.get("committee_approved")
            else:
                return "pass", "ok"
        elif c["type"] == "ca_election_default":
            ev, el = f.get("event_type"), f.get("election")
            if tgt == "scrip dividend":
                if ev != "scrip_dividend": return "pass", "ok"
                if el == "scrip":
                    scrip_ok = "not permitted" not in c["canonical_text"]
                    over = single_limit is not None and f.get("post_election_weight") is not None and float(f["post_election_weight"]) > single_limit + 1e-9
                    exceeded = (not scrip_ok) or (not f.get("rationale_provided")) or over
            elif tgt == "rights issue":
                if ev != "rights_issue": return "pass", "ok"
                exceeded = el in ("lapse", "sell_rights") and not f.get("rationale_provided")
            elif tgt == "tender offer":
                if ev != "tender_offer": return "pass", "ok"
                exceeded = el == "tender" and not f.get("cio_approved")
            elif tgt == "election deadline":
                if f.get("days_before_deadline") is None: return "pass", "ok"
                exceeded = float(f["days_before_deadline"]) < float(thr)
            else:
                return "pass", "ok"
    if exceeded:
        if c["hard"]:
            return "hard_block", "exceeded"
        if c["breach_action"] == "warn":
            return "warn", "soft_exceeded"
        return "breach", "exceeded"
    if in_band and c["breach_action"] != "warn":
        return "warn", "warn_band"
    return "pass", "ok"


def evaluate(scenario_like: dict, constraints: list[dict], documents: list[dict]) -> dict:
    """Compute Gold for a proposal. scenario_like needs fund, as_of, proposal, portfolio, doc_ids (list of doc_id in scope)."""
    as_of = scenario_like["as_of"]
    docs = {d["doc_id"]: d for d in documents}
    vif = {}
    in_force: list[dict] = []
    by_id = {c["id"]: c for c in constraints}
    for did in scenario_like["doc_ids"]:
        v = version_in_force(docs[did], as_of)
        if v is None: continue
        vif[did] = v
        ver = next(x for x in docs[did]["versions"] if x["version"] == v)
        in_force.extend(by_id[i] for i in ver["constraint_ids"] if not by_id[i].get("distractor"))
    st = post_trade(scenario_like["portfolio"], scenario_like["proposal"])
    st.flags["decision_type"] = scenario_like["proposal"]["decision_type"]
    single_limit = None
    for c in in_force:
        if c["type"] == "single_name_max" and c["scope"]["level"] == "fund":
            single_limit = float(effective_threshold(c, st))
    verdicts: dict[str, str] = {}; reasons: dict[str, str] = {}; in_scope: list[str] = []
    for c in in_force:
        val = exposure_value(c, st)
        if val is NA: continue
        in_scope.append(c["id"])
        v, r = evaluate_one(c, val, st, single_limit)
        verdicts[c["id"]] = v; reasons[c["id"]] = r
    overall = max(verdicts.values(), key=lambda v: SEVERITY[v]) if verdicts else "pass"
    hit = [i for i, v in verdicts.items() if v != "pass"]
    f = scenario_like["proposal"]["fields"]
    # approval path
    if overall == "pass":
        path = ["PM"]
    elif overall == "warn":
        path = ["PM", "CIO"]
    elif overall == "breach":
        allowed = True; approvers: set[str] = set()
        for i in hit:
            if verdicts[i] != "breach": continue
            c = by_id[i]
            ok = c["exception"]["allowed"]
            md = c["exception"].get("max_duration_days")
            if ok and f.get("duration_days") is not None and md is not None and float(f["duration_days"]) > md:
                ok = False
            allowed = allowed and ok
            approvers.update(c["exception"]["approvers"])
        path = [a for a in APPROVER_ORDER if a in approvers] if allowed else []
        if allowed and "PM" not in path:
            path = ["PM"] + path
    else:
        path = []
    # verb
    if overall == "pass":
        verb = "approve"
    elif overall == "warn":
        rs = {reasons[i] for i in hit}
        verb = "gather-more-data" if "missing_input" in rs else ("escalate" if "warn_band" in rs else "hold")
    elif overall == "breach":
        verb = "request-exception" if path else "reject"
    else:
        verb = "reject"
    return {"rules_in_scope": in_scope, "rules_hit": hit, "verdicts": verdicts, "overall": overall,
            "approval_path": path, "recommendation_verb": verb, "citable_constraint_ids": hit,
            "version_in_force": vif, "_reasons": reasons}
