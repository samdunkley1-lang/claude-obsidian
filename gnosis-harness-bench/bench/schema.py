"""Shared data contracts for the harness bench.

Everything on disk is JSON (specs, scenarios, results). These TypedDicts document the
shape; `validate_*` helpers enforce the parts graders depend on. Keep this file free of
any model or SDK imports so every other module can import it cheaply.
"""
from __future__ import annotations

from typing import Literal, TypedDict, NotRequired

FUNDS = ("GTF", "EIF", "DGF", "CBF", "EMF")
FUND_NAMES = {
    "GTF": "Midland Global Technology Fund",
    "EIF": "Midland European Income Fund",
    "DGF": "Midland Diversified Growth Fund",
    "CBF": "Midland Corporate Bond Fund",
    "EMF": "Midland Emerging Markets Fund",
}

DOC_TYPES = (
    "ips",                    # investment policy statement
    "guidelines",             # investment guidelines / mandate restrictions
    "derivatives_policy",
    "esg_policy",
    "liquidity_policy",
    "valuation_policy",
    "counterparty_policy",
    "corporate_actions_policy",
)

CONSTRAINT_TYPES = (
    "single_name_max", "issuer_max", "sector_max", "country_max",
    "cash_min", "cash_max", "duration_band", "credit_min_rating", "hy_max",
    "esg_exclusion", "derivatives_notional_max", "counterparty_max",
    "illiquid_max", "liquidity_min_daily", "tracking_error_max", "turnover_max",
    "position_count_min", "unhedged_fx_max", "swing_threshold",
    "valuation_lot_rule", "ca_election_default", "restricted_list",
)

Comparator = Literal["<=", ">=", "between", "prohibited", "required"]
Unit = Literal["pct_nav", "years", "rating", "count", "x", "bps", "days", "none"]
BreachAction = Literal["warn", "block", "hard_block"]
Verdict = Literal["pass", "warn", "breach", "hard_block"]
Verb = Literal["approve", "hold", "escalate", "request-exception", "reject", "gather-more-data"]

# Thirteen default decision types across six categories. These are the bench's own IDs;
# map them to gnosis's real decision-type IDs in config/decision_type_map.json once the
# repo is attached. Do not compare until that mapping is reviewed.
DECISION_TYPES = {
    "selection": ("single_name_overweight", "single_name_new_position", "exit_sell"),
    "allocation": ("sector_tilt", "country_tilt", "cash_level_change"),
    "rates_credit": ("duration_extension", "credit_quality_shift"),
    "hedging": ("fx_hedge_ratio_change", "derivatives_overlay"),
    "operations": ("corporate_action_election",),
    "governance": ("guideline_exception_request", "valuation_mark_override"),
}
ALL_DECISION_TYPES = tuple(t for ts in DECISION_TYPES.values() for t in ts)
assert len(ALL_DECISION_TYPES) == 13

VARIANT_KINDS = (
    "canonical",            # the primary rendering of the document version
    "paraphrase",           # same rule, different wording, same gold
    "adv_negation",         # "shall not exceed" vs "may not be less than" traps
    "adv_unless",           # exception clause changes the verdict
    "adv_superseded",       # old clause retained but marked superseded; gold uses new one
    "adv_crossref",         # threshold lives in a schedule referenced elsewhere
    "as_of_prior_version",  # scenario dated before an amendment; gold uses prior version
)


class Scope(TypedDict):
    level: Literal["fund", "sleeve", "issuer", "sector", "country", "rating_bucket"]
    target: NotRequired[str]


class ExceptionPolicy(TypedDict):
    allowed: bool
    approvers: list[str]          # e.g. ["PM", "CIO", "Compliance"]
    four_eyes: bool
    max_duration_days: NotRequired[int]


class Constraint(TypedDict):
    id: str                        # "GTF-guidelines-v1-C03"
    fund: str
    doc_id: str                    # "GTF-guidelines"
    version: int
    type: str                      # one of CONSTRAINT_TYPES
    scope: Scope
    comparator: Comparator
    threshold: float | list[float] | str | None
    unit: Unit
    effective_from: str            # ISO date
    effective_to: str | None
    breach_action: BreachAction
    warn_fraction: float | None    # warn when exposure >= warn_fraction * limit (for <=)
    exception: ExceptionPolicy
    hard: bool                     # hard gate: no exception path, admins cannot override
    canonical_text: str            # the sentence the renderer must reproduce in substance
    distractor: NotRequired[bool]  # true if this row is a non-binding lookalike (must NOT be extracted)
    carve_out: NotRequired["CarveOut"]  # conditional alternative threshold ("unless ...")


class CarveOut(TypedDict):
    condition_field: str           # proposal/portfolio field that triggers the carve-out, e.g. "benchmark_weight"
    condition_op: Literal[">", ">=", "==", "<", "<=", "is_true"]
    condition_value: float | str | bool
    alt_threshold: float | list[float] | str | None
    alt_text: str                  # the clause wording, e.g. "unless the issuer exceeds 3% of the benchmark, in which case benchmark weight plus 2%"


class DocumentVersion(TypedDict):
    version: int
    effective_from: str
    superseded_by: int | None
    constraint_ids: list[str]
    amendment_note: NotRequired[str]


class Rendering(TypedDict):
    rendering_id: str              # "GTF-guidelines-v1-canonical"
    doc_id: str
    version: int
    variant_kind: str              # one of VARIANT_KINDS (as_of_prior_version is scenario-level, not here)
    style: str                     # "legal", "bullets", "narrative", "tabular", "memo"
    path: str                      # relative path under data/corpus
    target_constraint_ids: NotRequired[list[str]]  # for adversarial variants: which rules are perturbed
    word_count: NotRequired[int]


class Document(TypedDict):
    doc_id: str
    fund: str
    doc_type: str
    title: str
    versions: list[DocumentVersion]
    renderings: list[Rendering]


class PortfolioState(TypedDict):
    nav_musd: float
    exposures: dict[str, float]    # keyed like "single_name:NVDA", "sector:Technology", "cash", "duration", "hy", ...
    holdings_count: int
    as_of: str


class Proposal(TypedDict):
    decision_type: str
    fields: dict[str, float | str | bool]   # schema-driven per decision type


class Gold(TypedDict):
    rules_in_scope: list[str]
    rules_hit: list[str]                    # constraints whose verdict is not "pass"
    verdicts: dict[str, Verdict]
    overall: Verdict
    approval_path: list[str]                # [] for hard_block (no path exists)
    recommendation_verb: Verb
    citable_constraint_ids: list[str]       # the rules a correct rationale must cite
    version_in_force: dict[str, int]        # doc_id -> version at as_of


class Scenario(TypedDict):
    scenario_id: str
    fund: str
    decision_type: str
    as_of: str
    proposal: Proposal
    portfolio: PortfolioState
    documents: list[str]                    # rendering_ids supplied to the system under test
    gold: Gold
    variant_kind: str
    variant_of: str | None
    tags: list[str]


# ---- what an adapter must return ---------------------------------------------------------

class Citation(TypedDict):
    rendering_id: str
    quote: str                     # verbatim text the model claims supports the point
    start_char: NotRequired[int]
    end_char: NotRequired[int]
    claims_constraint: NotRequired[str]     # constraint id the model says this supports, if any


class ExtractedConstraint(TypedDict):
    type: str
    scope: Scope
    comparator: str
    threshold: float | list[float] | str | None
    unit: str
    effective_from: str | None
    evidence: Citation


class IngestionOutput(TypedDict):
    constraints: list[ExtractedConstraint]


class RuleHit(TypedDict):
    type: str                      # constraint type from CONSTRAINT_TYPES
    scope: Scope
    verdict: str                   # pass|warn|breach|hard_block
    limit: NotRequired[float | list[float] | str | None]
    exposure_post_trade: NotRequired[float | None]


class VerdictOutput(TypedDict):
    rules_hit: list[RuleHit]       # graders match to gold constraints by (type, scope.level, scope.target)
    overall: str
    approval_path: list[str]
    recommendation_verb: str
    rationale: str
    citations: list[Citation]


class RunMeta(TypedDict):
    model_requested: str
    model_served: str | None
    stop_reason: str | None
    usage: dict[str, int]
    latency_ms: float
    attempts: int
    condition_config_hash: str


class ResultRow(TypedDict):
    case_id: str
    task: Literal["ingestion", "verdict"]
    condition: str
    rep: int
    status: Literal["ok", "truncated", "refusal"]
    grades: dict[str, float | None]
    meta: RunMeta
    trajectory_path: str


class ErrorRow(TypedDict):
    case_id: str
    task: str
    condition: str
    rep: int
    failure_class: Literal["harness_error", "api_error", "timeout", "unparseable", "model_mismatch", "grader_error"]
    detail: str


def validate_constraint(c: dict) -> None:
    assert c["fund"] in FUNDS, c
    assert c["type"] in CONSTRAINT_TYPES, c["type"]
    assert c["comparator"] in ("<=", ">=", "between", "prohibited", "required"), c
    assert c["breach_action"] in ("warn", "block", "hard_block"), c
    if c["hard"]:
        assert c["breach_action"] == "hard_block" and not c["exception"]["allowed"], c["id"]
    if c["comparator"] == "between":
        assert isinstance(c["threshold"], list) and len(c["threshold"]) == 2, c["id"]


def validate_scenario(s: dict) -> None:
    assert s["fund"] in FUNDS
    assert s["decision_type"] in ALL_DECISION_TYPES, s["decision_type"]
    g = s["gold"]
    assert g["overall"] in ("pass", "warn", "breach", "hard_block")
    assert g["recommendation_verb"] in ("approve", "hold", "escalate", "request-exception", "reject", "gather-more-data")
    if g["overall"] == "hard_block":
        assert g["approval_path"] == [], s["scenario_id"]
    assert s["variant_kind"] in VARIANT_KINDS
