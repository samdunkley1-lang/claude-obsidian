# Pre-registration: gnosis harness bench

Status: LOCKED 2026-09-20 before any live model run. Changes after this date go in the "Amendments" section with a date and reason, never by editing the locked text.

## Question

Does the gnosis harness (typed capture, deterministic policy engine, validated prose, precedent context) make the same foundation model more accurate, better grounded and more consistent at (a) extracting binding rules from investment policy documents and (b) evaluating a proposed decision against those rules, than the vendor's own harness given the same documents, and which components carry the lift?

## Design

Paired, within-case comparison. Every case is run under every condition; differences are computed per case and bootstrapped at the case level. The model is held constant (`claude-opus-5`, effort high, adaptive thinking default, no fallbacks); `response.model` is asserted on every call. Reps: 5 per (case, condition). Execution order interleaves conditions so time-of-day effects do not align with a condition.

| Condition | Description | Status |
|---|---|---|
| oracle | Gold echoed back through the output shape | Instrument check, must score 1.0 |
| null | Constant "pass / approve / no rules" | Instrument check, must score ~0 on discriminating metrics |
| H0 | Bare model, documents pasted as text, free-form JSON | Floor |
| H1 | Vendor harness, fair: document blocks with citations enabled, strict tool schema | Primary baseline |
| H2 | H1 plus BM25 retrieval of top-12 chunks | Retrieval control |
| G | gnosis full | Primary treatment (requires gnosis repo) |
| G-schema, G-engine, G-validator, G-precedent | gnosis with one component disabled | Attribution (requires gnosis repo) |

## Case sets

| Set | Task | n | Role |
|---|---|---|---|
| ING-A | ingestion, canonical renderings | 57 | primary |
| ING-B | ingestion, paraphrase and adversarial renderings | 37 | secondary |
| VER-A | verdict, canonical scenarios | 324 | primary |
| VER-B | verdict, rendering-swap variants (paraphrase, negation, unless, superseded, crossref) | 492 | secondary, robustness |
| VER-C | verdict, both document versions supplied (as-of) | 34 | primary for H5 |
| VER-H | verdict, gold overall = hard_block | 44 | primary for H6 |

Gold is computed by construction from structured specs (`bench/generate_specs.py`) by the reference engine (`bench/reference_engine.py`, semantics in `bench/policy_semantics.md`). Labels are exact; the rendering fidelity of the prose is audited separately (see Label quality).

## Primary hypotheses (confirmatory)

All tested as paired differences G minus H1 on set VER-A unless stated. Direction is pre-specified. Holm-Bonferroni across the six.

| # | Metric | Set | Hypothesis | Smallest effect worth acting on |
|---|---|---|---|---|
| H1 | constraint_f1 | ING-A | G > H1 | 0.05 |
| H2 | overall_correct | VER-A | G > H1 | 0.05 |
| H3 | citable_coverage | VER-A | G > H1 | 0.05 |
| H4 | pass^5 on overall_correct | VER-A | G > H1 | 0.05 |
| H5 | version_in_force_respected | VER-C | G > H1 | 0.10 |
| H6 | hard_block_correct, fail-on-any over reps | VER-H | G = 1.00; H1 < 1.00 | any miss |

Decision rule: a hypothesis is supported if the Holm-adjusted two-sided bootstrap p is below 0.05 and the 95% CI of the difference excludes zero in the predicted direction. Reported regardless of outcome.

## Secondary analyses (exploratory, labelled as such)

- H1 versus H0 and H2 versus H1 on every primary metric (how much the vendor harness itself adds).
- Attribution: G minus each G-minus-component condition on the metric that component targets (schema: rules_hit_f1; engine: overall_correct and pass^5; validator: citation_grounded and causal_clean; precedent: verb_correct).
- Robustness on VER-B by variant kind: agreement of the model's own verdict between the canonical and each variant (majority over reps), plus correctness.
- hard_block_no_false_alarm, approval_path_correct, verb_correct, rule_verdict_accuracy, evidence_misgrounded_rate.
- Cost and latency per condition from recorded usage.

## Power

From `bench/stats.noise_floor` and `bench/stats.mde_paired` (simulation, beta-binomial case heterogeneity, rho_case 0.5, power 0.8, alpha 0.05):

| n cases | reps | half-width of a pass rate (rho 0.3 to 0.7) | paired MDE at baseline 0.70 |
|---|---|---|---|
| 324 (VER-A) | 5 | 0.033 to 0.044 | 0.05 |
| 200 | 5 | 0.042 to 0.055 | 0.06 |
| 100 | 5 | 0.060 to 0.078 | 0.09 |
| 44 (VER-H) | 5 | 0.069 (rho 0.5) | n/a, fail-on-any |

The primary sets are sized so the MDE equals the smallest effect worth acting on.

## Exclusions and error handling

- Rows with status `truncated` or `refusal` are excluded from quality estimates and their counts reported per condition.
- API errors, timeouts, unparseable outputs and model mismatches go to `errors.jsonl` with a failure class and never into results. If any condition loses more than 5% of its (case, rep) slots to errors, the run is repeated for that condition before analysis.
- Grades of None (metric not applicable) are skipped, not scored as zero.

## Instrument validation (must pass before any live run)

1. `oracle` scores 1.0 on every applicable metric; `null` scores 0 on overall_correct for non-pass cases and 0 on constraint_recall.
2. Statistical estimators pass the coverage simulations in `tests/test_stats.py` (Wilson, case-level bootstrap, paired bootstrap at 93 to 98 percent coverage).
3. Mechanism check on the mock adapter: lowering `p_ground` must lower citation_grounded; lowering `p_correct` must lower overall_correct.
4. Label quality: a blind re-extraction of a stratified sample of at least 20 renderings (independent reader, no access to specs) must reach constraint-level agreement of 0.90 or better with the specs. Below that, the corpus is fixed and re-audited before the live run.

## Blinding and graders

All primary graders are deterministic code (`bench/graders.py`). No LLM judge contributes to a primary metric. Ground truth is never in any prompt.

## Reporting

`bench/report.py` recomputes every headline from raw rows. The report carries: per-condition estimates with case-level bootstrap CIs and Wilson intervals, paired differences with CIs and Holm-adjusted p-values, pass^k, fail-on-any on VER-H, robustness by variant kind, excluded-row counts, token usage and cost per condition, and the run manifest (git commit, data hashes, adapter config hashes, model served).

## Stopping rules

One full pass over the pre-specified sets. No interim looks. A second pass is run only if an instrument defect is found and documented in Amendments.

## Amendments

(none)
