# Policy semantics (reference)

These rules define gold verdicts. The reference engine implements them; the system prompts given to every LLM condition describe them in the same words so that only the harness varies.

## Evaluating one constraint at an as-of date
- The version in force is the latest document version whose effective_from is on or before the scenario's as_of date.
- Exposure is measured post-trade: portfolio exposure plus the change the proposal would make.
- A position change moves cash by the opposite amount (a purchase reduces cash, a sale adds to cash) unless the proposal states `funded_from_cash: false`, in which case the change is offset pro rata against other holdings and cash is unchanged.
- `<=` limit L with warn fraction w: exposure > L is a breach; w*L <= exposure <= L is a warn; below is a pass.
- `>=` floor F with warn fraction w: exposure < F is a breach; F <= exposure < F*(2-w) is a warn; above is a pass.
- `between` [lo, hi] with warn fraction w: outside the band is a breach; within the outer (1-w) fraction of the band width of either edge is a warn; otherwise a pass.
- `prohibited`: any post-trade exposure above zero to the prohibited target is a breach.
- `required`: the proposal must satisfy the stated condition; otherwise it is a breach.
- A carve-out ("unless ...") replaces the threshold with the alternative threshold when its condition holds.
- If the constraint's breach_action is `warn`, an exceeded limit yields `warn`, never `breach`.
- If the constraint is `hard` (breach_action `hard_block`), an exceeded limit yields `hard_block`. No exception or approval can clear it.
- A constraint that cannot be evaluated because the proposal lacks a required field is recorded as `warn` with reason `missing_input`.

## Overall verdict
Severity order: hard_block > breach > warn > pass. The overall verdict is the most severe rule verdict.

## Approval path
- pass: ["PM"]
- warn: ["PM", "CIO"]
- breach: the union of the exception approvers of every breached rule, ordered PM, CIO, Compliance, Risk, ValuationCommittee. If any breached rule does not allow exceptions, no path exists: [].
- hard_block: [] (no path exists).

## Recommendation verb
- pass: approve
- warn caused only by soft rules being exceeded (breach_action `warn`): hold
- warn caused by an approach to a blocking limit (inside the warn band): escalate
- warn caused by missing input: gather-more-data
- breach where every breached rule allows an exception: request-exception
- breach where any breached rule disallows exceptions: reject
- hard_block: reject

## Citations
A correct rationale cites, for every rule that is warn, breach or hard_block, the document text that states the limit. A citation is grounded if its quote appears verbatim in the supplied document, and relevant if the quote contains the limit value (or the prohibited item).

## Rationale language
Rationales must not assert causation about market behaviour. Banned phrases: "driven by", "caused by", "because of the market", "as a result of", "led to", "due to the". Rationales may only reference identifiers that exist in the supplied documents or the scenario.
