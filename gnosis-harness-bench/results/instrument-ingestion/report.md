# Bench report: instrument-ingestion

Task: **ingestion**. Conditions: oracle, null, mock:p=0.9,g=0.9, mock:p=0.5,g=0.5. Reps: 5. Seed: 0. Cases: 94. Git HEAD: `24d2d5b026e5a14c45de2c19d56547b6aae79f11`. Started: 2026-09-20T11:33:35.849514+00:00.

## Excluded rows

Rows with status `truncated` or `refusal` carry grades but are excluded from every statistic below; error rows have no grades.

| condition | ok | truncated (excluded) | refusal (excluded) | errors (excluded) | error classes |
|---|---|---|---|---|---|
| oracle | 470 | 0 | 0 | 0 | none |
| null | 470 | 0 | 0 | 0 | none |
| mock:p=0.9,g=0.9 | 470 | 0 | 0 | 0 | none |
| mock:p=0.5,g=0.5 | 470 | 0 | 0 | 0 | none |

## Metrics by condition

Mean over `ok` rows, all reps pooled. `n/a` means the metric did not apply to any row.

| metric | oracle | null | mock:p=0.9,g=0.9 | mock:p=0.5,g=0.5 |
|---|---|---|---|---|
| constraint_precision | 1.000 [1.000, 1.000] (n=94) | n/a (n=0) | 0.977 [0.970, 0.985] (n=94) | 0.853 [0.831, 0.875] (n=94) |
| constraint_recall | 1.000 [1.000, 1.000] (n=94) | 0.000 [0.000, 0.000] (n=94) | 0.965 [0.954, 0.976] (n=94) | 0.781 [0.751, 0.809] (n=94) |
| constraint_f1 | 1.000 [1.000, 1.000] (n=94) | 0.000 [0.000, 0.000] (n=94) | 0.970 [0.961, 0.980] (n=94) | 0.812 [0.786, 0.838] (n=94) |
| threshold_exact | 1.000 [1.000, 1.000] (n=94) | n/a (n=0) | 0.977 [0.970, 0.985] (n=94) | 0.853 [0.831, 0.875] (n=94) |
| scope_attribution | 1.000 [1.000, 1.000] (n=94) | 0.000 [0.000, 0.000] (n=94) | 0.982 [0.977, 0.988] (n=94) | 0.890 [0.876, 0.905] (n=94) |
| effective_date_exact | 1.000 [1.000, 1.000] (n=94) | n/a (n=0) | 1.000 [1.000, 1.000] (n=94) | 1.000 [1.000, 1.000] (n=94) |
| distractor_excluded | 1.000 [1.000, 1.000] (n=94) | 1.000 [1.000, 1.000] (n=94) | 1.000 [1.000, 1.000] (n=94) | 1.000 [1.000, 1.000] (n=94) |
| evidence_grounded | 1.000 [1.000, 1.000] (n=94) | n/a (n=0) | 0.895 [0.882, 0.908] (n=94) | 0.495 [0.471, 0.519] (n=94) |
| evidence_relevant | 1.000 [1.000, 1.000] (n=94) | n/a (n=0) | 1.000 [1.000, 1.000] (n=94) | 1.000 [1.000, 1.000] (n=94) |
| evidence_misgrounded_rate | 0.000 [0.000, 0.000] (n=94) | n/a (n=0) | 0.000 [0.000, 0.000] (n=94) | 0.000 [0.000, 0.000] (n=94) |
| evidence_ungrounded_rate | 0.000 [0.000, 0.000] (n=94) | n/a (n=0) | 0.105 [0.092, 0.118] (n=94) | 0.505 [0.481, 0.529] (n=94) |

## Paired differences versus baseline `mock:p=0.5,g=0.5`

Difference is condition minus baseline on per-case means; CI and p from paired bootstrap; p_holm is Holm-adjusted across every (condition, metric) pair in this table.

| condition | metric | diff | ci_lo | ci_hi | p_boot | p_holm | n_cases | mcnemar p |
|---|---|---|---|---|---|---|---|---|
| oracle | constraint_f1 | 0.188 | 0.162 | 0.214 | 0.000 | 0.000 | 94 | n/a |
| oracle | evidence_grounded | 0.505 | 0.481 | 0.528 | 0.000 | 0.000 | 94 | n/a |
| null | constraint_f1 | -0.812 | -0.838 | -0.786 | 0.000 | 0.000 | 94 | n/a |
| null | evidence_grounded | n/a | n/a | n/a | n/a | n/a | 0 | n/a |
| mock:p=0.9,g=0.9 | constraint_f1 | 0.158 | 0.132 | 0.185 | 0.000 | 0.000 | 94 | n/a |
| mock:p=0.9,g=0.9 | evidence_grounded | 0.400 | 0.371 | 0.428 | 0.000 | 0.000 | 94 | n/a |

## pass^k (k = 5) on overall_correct

_overall_correct is not graded for this task._

## Hard gate: fail on any

| condition | hard_block cases | share with every rep correct |
|---|---|---|
| oracle | 0 | n/a |
| null | 0 | n/a |
| mock:p=0.9,g=0.9 | 0 | n/a |
| mock:p=0.5,g=0.5 | 0 | n/a |

## Paraphrase robustness

Groups are scenarios sharing a `variant_of`. Verdicts are the majority over reps. A group counts as robust when each variant's verdict agrees with the canonical's exactly when their gold verdicts agree (paraphrase-type variants must match; as_of_prior_version and other gold-changing variants must differ).

_Not a verdict run; paraphrase robustness does not apply._
