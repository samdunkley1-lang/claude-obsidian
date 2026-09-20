# Bench report: instrument-verdict

Task: **verdict**. Conditions: oracle, null, mock:p=0.9,g=0.9, mock:p=0.5,g=0.5. Reps: 5. Seed: 0. Cases: 833. Git HEAD: `24d2d5b026e5a14c45de2c19d56547b6aae79f11`. Started: 2026-09-20T11:32:16.009351+00:00.

## Excluded rows

Rows with status `truncated` or `refusal` carry grades but are excluded from every statistic below; error rows have no grades.

| condition | ok | truncated (excluded) | refusal (excluded) | errors (excluded) | error classes |
|---|---|---|---|---|---|
| oracle | 4165 | 0 | 0 | 0 | none |
| null | 4165 | 0 | 0 | 0 | none |
| mock:p=0.9,g=0.9 | 4165 | 0 | 0 | 0 | none |
| mock:p=0.5,g=0.5 | 4165 | 0 | 0 | 0 | none |

## Metrics by condition

Mean over `ok` rows, all reps pooled. `n/a` means the metric did not apply to any row.

| metric | oracle | null | mock:p=0.9,g=0.9 | mock:p=0.5,g=0.5 |
|---|---|---|---|---|
| overall_correct | 1.000 [1.000, 1.000] (n=833) | 0.329 [0.295, 0.361] (n=833) | 0.901 [0.892, 0.910] (n=833) | 0.489 [0.473, 0.503] (n=833) |
| severity_distance | 1.000 [1.000, 1.000] (n=833) | 0.609 [0.587, 0.631] (n=833) | 0.967 [0.964, 0.970] (n=833) | 0.830 [0.824, 0.834] (n=833) |
| hard_block_correct | 1.000 [1.000, 1.000] (n=44) | 0.000 [0.000, 0.000] (n=44) | 0.927 [0.900, 0.955] (n=44) | 0.441 [0.377, 0.505] (n=44) |
| hard_block_false_alarm | 0.000 [0.000, 0.000] (n=789) | 0.000 [0.000, 0.000] (n=789) | 0.022 [0.018, 0.027] (n=789) | 0.111 [0.098, 0.124] (n=789) |
| hard_block_no_false_alarm | 1.000 [1.000, 1.000] (n=789) | 1.000 [1.000, 1.000] (n=789) | 0.978 [0.973, 0.982] (n=789) | 0.889 [0.876, 0.902] (n=789) |
| rules_hit_precision | 1.000 [1.000, 1.000] (n=559) | n/a (n=0) | 1.000 [1.000, 1.000] (n=559) | 1.000 [1.000, 1.000] (n=542) |
| rules_hit_recall | 1.000 [1.000, 1.000] (n=559) | 0.000 [0.000, 0.000] (n=559) | 0.908 [0.897, 0.918] (n=559) | 0.535 [0.515, 0.554] (n=559) |
| rules_hit_f1 | 1.000 [1.000, 1.000] (n=559) | 0.000 [0.000, 0.000] (n=559) | 0.910 [0.900, 0.921] (n=559) | 0.549 [0.528, 0.569] (n=559) |
| rule_verdict_accuracy | 1.000 [1.000, 1.000] (n=559) | n/a (n=0) | 1.000 [1.000, 1.000] (n=559) | 1.000 [1.000, 1.000] (n=542) |
| approval_path_correct | 1.000 [1.000, 1.000] (n=833) | 0.329 [0.295, 0.361] (n=833) | 0.903 [0.894, 0.912] (n=833) | 0.496 [0.481, 0.511] (n=833) |
| verb_correct | 1.000 [1.000, 1.000] (n=833) | 0.329 [0.295, 0.361] (n=833) | 0.901 [0.892, 0.910] (n=833) | 0.489 [0.473, 0.503] (n=833) |
| citation_grounded | 1.000 [1.000, 1.000] (n=559) | n/a (n=0) | 0.905 [0.894, 0.915] (n=559) | 0.491 [0.474, 0.508] (n=559) |
| citation_relevant | 1.000 [1.000, 1.000] (n=559) | n/a (n=0) | 1.000 [1.000, 1.000] (n=559) | 1.000 [1.000, 1.000] (n=543) |
| citable_coverage | 1.000 [1.000, 1.000] (n=559) | 0.000 [0.000, 0.000] (n=559) | 0.906 [0.895, 0.916] (n=559) | 0.494 [0.477, 0.511] (n=559) |
| citations_present | 1.000 [1.000, 1.000] (n=559) | 0.000 [0.000, 0.000] (n=559) | 1.000 [1.000, 1.000] (n=559) | 1.000 [1.000, 1.000] (n=559) |
| causal_clean | 1.000 [1.000, 1.000] (n=833) | 1.000 [1.000, 1.000] (n=833) | 1.000 [1.000, 1.000] (n=833) | 1.000 [1.000, 1.000] (n=833) |
| references_bound | 1.000 [1.000, 1.000] (n=833) | 1.000 [1.000, 1.000] (n=833) | 1.000 [1.000, 1.000] (n=833) | 1.000 [1.000, 1.000] (n=833) |
| version_in_force_respected | 1.000 [1.000, 1.000] (n=34) | 0.118 [0.029, 0.235] (n=34) | 0.924 [0.876, 0.965] (n=34) | 0.565 [0.476, 0.659] (n=34) |

## Paired differences versus baseline `mock:p=0.5,g=0.5`

Difference is condition minus baseline on per-case means; CI and p from paired bootstrap; p_holm is Holm-adjusted across every (condition, metric) pair in this table.

| condition | metric | diff | ci_lo | ci_hi | p_boot | p_holm | n_cases | mcnemar p |
|---|---|---|---|---|---|---|---|---|
| oracle | overall_correct | 0.511 | 0.496 | 0.526 | 0.000 | 0.000 | 833 | 0.000 |
| oracle | citable_coverage | 0.506 | 0.490 | 0.524 | 0.000 | 0.000 | 559 | n/a |
| oracle | hard_block_correct | 0.559 | 0.495 | 0.618 | 0.000 | 0.000 | 44 | 0.000 |
| null | overall_correct | -0.160 | -0.194 | -0.125 | 0.000 | 0.000 | 833 | 0.000 |
| null | citable_coverage | -0.494 | -0.510 | -0.476 | 0.000 | 0.000 | 559 | n/a |
| null | hard_block_correct | -0.441 | -0.505 | -0.382 | 0.000 | 0.000 | 44 | 0.000 |
| mock:p=0.9,g=0.9 | overall_correct | 0.413 | 0.395 | 0.430 | 0.000 | 0.000 | 833 | 0.000 |
| mock:p=0.9,g=0.9 | citable_coverage | 0.412 | 0.393 | 0.433 | 0.000 | 0.000 | 559 | n/a |
| mock:p=0.9,g=0.9 | hard_block_correct | 0.486 | 0.414 | 0.559 | 0.000 | 0.000 | 44 | 0.000 |

## pass^k (k = 5) on overall_correct

| condition | pass^k | ci_lo | ci_hi |
|---|---|---|---|
| oracle | 1.000 | 1.000 | 1.000 |
| null | 0.329 | 0.298 | 0.361 |
| mock:p=0.9,g=0.9 | 0.599 | 0.567 | 0.633 |
| mock:p=0.5,g=0.5 | 0.026 | 0.016 | 0.037 |

## Hard gate: fail on any

| condition | hard_block cases | share with every rep correct |
|---|---|---|
| oracle | 44 | 1.000 |
| null | 44 | 0.000 |
| mock:p=0.9,g=0.9 | 44 | 0.636 |
| mock:p=0.5,g=0.5 | 44 | 0.023 |

## Paraphrase robustness

Groups are scenarios sharing a `variant_of`. Verdicts are the majority over reps. A group counts as robust when each variant's verdict agrees with the canonical's exactly when their gold verdicts agree (paraphrase-type variants must match; as_of_prior_version and other gold-changing variants must differ).

| condition | adv_crossref | adv_negation | adv_superseded | adv_unless | as_of_prior_version | paraphrase |
|---|---|---|---|---|---|---|
| oracle | 1.000 (n=27) | 1.000 (n=65) | 1.000 (n=170) | 1.000 (n=6) | 1.000 (n=17) | 1.000 (n=224) |
| null | 1.000 (n=27) | 1.000 (n=65) | 1.000 (n=170) | 1.000 (n=6) | 0.118 (n=17) | 1.000 (n=224) |
| mock:p=0.9,g=0.9 | 1.000 (n=27) | 0.985 (n=65) | 0.976 (n=170) | 1.000 (n=6) | 1.000 (n=17) | 0.978 (n=224) |
| mock:p=0.5,g=0.5 | 0.556 (n=27) | 0.554 (n=65) | 0.518 (n=170) | 0.667 (n=6) | 0.941 (n=17) | 0.451 (n=224) |
