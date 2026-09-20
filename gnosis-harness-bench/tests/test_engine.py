"""Hand-computed checks of the reference policy engine and generator invariants."""
import json
from pathlib import Path

import pytest

from bench.reference_engine import evaluate, version_in_force
from bench.generate_specs import generate
from bench.generate_scenarios import Ctx, build
from bench.render_plan import build_plan

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def specs():
    cons, docs = generate(0)
    plan = build_plan(cons, docs)
    return cons, docs, plan


def mk(fund, dt, fields, as_of="2026-06-15", cash=6.0):
    ex = {"cash": cash, "single_name:NVDA": 4.0, "issuer:NVIDIA": 4.0, "sector:Semiconductors": 20.0, "country:United States": 40.0}
    return {"fund": fund, "as_of": as_of, "proposal": {"decision_type": dt, "fields": fields},
            "portfolio": {"nav_musd": 1000.0, "exposures": ex, "holdings_count": 55, "as_of": as_of},
            "doc_ids": [f"{fund}-{d}" for d in ("ips", "guidelines", "derivatives_policy", "esg_policy", "liquidity_policy", "valuation_policy", "counterparty_policy", "corporate_actions_policy")]}


def test_version_in_force(specs):
    cons, docs, _ = specs
    g = next(d for d in docs if d["doc_id"] == "GTF-guidelines")
    assert version_in_force(g, "2026-02-15") == 1
    assert version_in_force(g, "2026-04-01") == 2
    assert version_in_force(g, "2024-12-31") is None


def test_single_name_pass_warn_breach_hard(specs):
    cons, docs, _ = specs
    base = dict(ticker="NVDA", issuer="NVIDIA", sector="Semiconductors", country="United States", current_weight=4.0, benchmark_weight=1.0, restricted=False, funded_from_cash=False)
    # GTF guidelines v2 (as of 2026-06-15): single name 7%, warn band from 6.3%
    g = evaluate(mk("GTF", "single_name_overweight", {**base, "target_weight": 6.0}), cons, docs)
    assert g["overall"] == "pass" and g["approval_path"] == ["PM"] and g["recommendation_verb"] == "approve"
    g = evaluate(mk("GTF", "single_name_overweight", {**base, "target_weight": 6.5}), cons, docs)
    assert g["overall"] == "warn" and g["recommendation_verb"] == "escalate" and g["approval_path"] == ["PM", "CIO"]
    g = evaluate(mk("GTF", "single_name_overweight", {**base, "target_weight": 7.5}), cons, docs)
    assert g["overall"] == "breach" and g["recommendation_verb"] == "request-exception" and g["approval_path"] == ["PM", "CIO", "Compliance"]
    g = evaluate(mk("GTF", "single_name_overweight", {**base, "target_weight": 6.0, "restricted": True}), cons, docs)
    assert g["overall"] == "hard_block" and g["approval_path"] == [] and g["recommendation_verb"] == "reject"
    assert any(i.startswith("GTF-guidelines-v2") and cons_by(cons)[i]["type"] == "restricted_list" for i in g["rules_hit"])


def cons_by(cons):
    return {c["id"]: c for c in cons}


def test_as_of_uses_prior_version(specs):
    cons, docs, _ = specs
    base = dict(ticker="NVDA", issuer="NVIDIA", sector="Semiconductors", country="United States", current_weight=4.0, benchmark_weight=1.0, restricted=False, funded_from_cash=False, target_weight=7.5)
    v1 = evaluate(mk("GTF", "single_name_overweight", base, as_of="2026-02-15"), cons, docs)   # limit 8% -> 7.5 is in the warn band (>= 7.2)
    v2 = evaluate(mk("GTF", "single_name_overweight", base, as_of="2026-06-15"), cons, docs)   # limit 7% -> breach
    assert v1["overall"] == "warn" and v2["overall"] == "breach"
    assert v1["version_in_force"]["GTF-guidelines"] == 1 and v2["version_in_force"]["GTF-guidelines"] == 2


def test_carve_out_lifts_single_name_limit(specs):
    cons, docs, _ = specs
    base = dict(ticker="NVDA", issuer="NVIDIA", sector="Semiconductors", country="United States", current_weight=4.0, restricted=False, funded_from_cash=False, target_weight=8.5)
    no_carve = evaluate(mk("GTF", "single_name_overweight", {**base, "benchmark_weight": 1.0}), cons, docs)
    carve = evaluate(mk("GTF", "single_name_overweight", {**base, "benchmark_weight": 8.0}), cons, docs)  # alt limit = 8 + 2 = 10, warn band from 9
    assert no_carve["overall"] == "breach" and carve["overall"] == "pass"


def test_exception_duration_beyond_max_rejects(specs):
    cons, docs, _ = specs
    ok = evaluate(mk("DGF", "guideline_exception_request", dict(constraint_type="single_name_max", scope_level="fund", requested_exposure=5.0, duration_days=20)), cons, docs)
    bad = evaluate(mk("DGF", "guideline_exception_request", dict(constraint_type="single_name_max", scope_level="fund", requested_exposure=5.0, duration_days=45)), cons, docs)
    assert ok["recommendation_verb"] == "request-exception" and ok["approval_path"] == ["PM", "CIO", "Compliance"]
    assert bad["recommendation_verb"] == "reject" and bad["approval_path"] == []


def test_missing_input_gathers_more_data(specs):
    cons, docs, _ = specs
    g = evaluate(mk("CBF", "duration_extension", {"current_duration": 5.0}), cons, docs)
    assert g["overall"] == "warn" and g["recommendation_verb"] == "gather-more-data"


def test_soft_rule_exceeded_is_hold(specs):
    cons, docs, _ = specs
    f = dict(ticker="NVDA", issuer="NVIDIA", sector="Semiconductors", country="United States", current_weight=4.0, restricted=False, funded_from_cash=False, days_before_deadline=1, event_type="rights_issue", election="take_up")
    g = evaluate(mk("GTF", "corporate_action_election", f), cons, docs)
    assert g["overall"] == "warn" and g["recommendation_verb"] == "hold"


def test_generator_is_deterministic_and_valid(specs):
    cons, docs, plan = specs
    a = build(Ctx(cons, docs, plan), 0); b = build(Ctx(cons, docs, plan), 0)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert all(s["gold"]["approval_path"] == [] for s in a if s["gold"]["overall"] == "hard_block")
    assert all(s["gold"]["recommendation_verb"] == "approve" for s in a if s["gold"]["overall"] == "pass")


def test_shipped_scenarios_match_regenerated(specs):
    p = ROOT / "data" / "scenarios" / "scenarios.jsonl"
    if not p.exists():
        pytest.skip("scenarios not generated")
    cons, docs, plan = specs
    shipped = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    regen = build(Ctx(cons, docs, plan), 0)
    assert json.dumps(shipped, sort_keys=True) == json.dumps(regen, sort_keys=True)
