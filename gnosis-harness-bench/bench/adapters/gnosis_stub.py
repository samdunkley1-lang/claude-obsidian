"""Gnosis conditions (G, G-schema, G-engine, G-validator, G-precedent): not yet wired.

Running any of these raises ``NotImplementedError``. The integration points required from
the gnosis repo, and how each maps to the ablation conditions, are:

Integration points
------------------
1. ``evaluate_policy(proposal, portfolio, as_of, documents) -> VerdictOutput``
   The policy evaluation call. Input: the scenario's proposal (decision_type plus fields),
   the PortfolioState, the as_of date, and the supplied renderings (rendering_id, text).
   Output must be converted to ``schema.VerdictOutput``: rules_hit as RuleHit dicts (type,
   scope, verdict, limit, exposure_post_trade), overall, approval_path, recommendation_verb,
   rationale and citations (rendering_id, quote, claims_constraint). The bench decision type
   ids must be mapped to gnosis decision-type ids through config/decision_type_map.json.
2. ``ingest_document(rendering_id, text) -> IngestionOutput``
   The ingestion call. Input: one rendering. Output: ``schema.IngestionOutput`` with one
   ExtractedConstraint per rule, each carrying verbatim evidence from the rendering.
3. Config flags for the ablations (passed to both calls):
   ``use_typed_schema``  - constrain model output to the typed constraint / verdict schema
   ``use_policy_engine`` - evaluate rules with the deterministic policy engine instead of
                           asking the model for verdicts
   ``use_validator``     - run the post-hoc validator (grounding, identifier binding,
                           causal-language checks) and repair or reject outputs
   ``use_precedents``    - retrieve prior decisions (DEC-* records) as precedents
4. ``model_served`` must be read from the underlying API response so the runner can
   assert the model.

Condition mapping
-----------------
    G            all four flags on (the full gnosis harness)
    G-schema     use_typed_schema=False, others on   (ablate the typed schema)
    G-engine     use_policy_engine=False, others on  (ablate the policy engine)
    G-validator  use_validator=False, others on      (ablate the validator)
    G-precedent  use_precedents=False, others on     (ablate precedent retrieval)

The registry in ``bench/adapters/__init__.py`` already instantiates this class with those
flag combinations, so wiring the two calls in ``_run`` is the only change needed.
"""
from __future__ import annotations

from bench.adapters.base import Adapter

ABLATION_FLAGS = ("use_typed_schema", "use_policy_engine", "use_validator", "use_precedents")


class GnosisStubAdapter(Adapter):
    adapter_name = "gnosis"

    def __init__(self, name: str | None = None, config: dict | None = None) -> None:
        cfg = {flag: True for flag in ABLATION_FLAGS}
        cfg.update(config or {})
        super().__init__(name, cfg)
        self.flags = {flag: bool(self.config[flag]) for flag in ABLATION_FLAGS}
        self.requested_model = None  # set from the gnosis model config once wired

    def _run(self, case: dict, task: str, rep: int, seed: int) -> tuple[dict, dict, dict]:
        raise NotImplementedError(
            "gnosis integration not wired: see bench/adapters/gnosis_stub.py for the required "
            f"integration points (flags={self.flags})"
        )
