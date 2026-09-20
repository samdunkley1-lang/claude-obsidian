---
type: source
title: "Gnosis Harness Bench"
source_type: benchmark
created: 2026-09-20
updated: 2026-09-20
tags:
  - gnosis
  - benchmark
  - evaluation
  - statistics
status: current
related:
  - "[[gnosis/_index]]"
  - "[[gnosis-decision-ui-benchmarks]]"
raw_file: "gnosis-harness-bench/"
---

# Gnosis Harness Bench

A controlled, pre-registered ablation that measures what the gnosis harness adds to a foundation model versus the vendor's own harness, on rule ingestion from policy documents and on decision verdicts with grounded citations. Code and data live in `gnosis-harness-bench/` at the repo root; the protocol is locked in `PREREGISTRATION.md`.

## Design in one table

| Element | Value |
|---|---|
| Model held constant | claude-opus-5, effort high, no fallbacks, response model asserted |
| Conditions | oracle, null, mock (instrument); H0 bare, H1 vendor harness with citations and strict schema, H2 plus BM25 retrieval; G and four G-minus ablations (need the gnosis repo) |
| Ground truth | 5 funds x 8 policy documents, 57 versions, 301 binding rules, 66 distractors, 22 hard gates, 8 carve-outs; gold verdicts by a deterministic reference engine |
| Corpus | 94 prose renderings (canonical, paraphrase, negation, unless, superseded, cross-reference), 71,745 words, verifier clean |
| Scenarios | 833 (324 canonical, 492 rendering-swap variants, 17 as-of-prior-version, 44 hard-gate) |
| Reps and analysis | 5 reps; case-level and paired bootstrap, exact McNemar, pass^k, Holm; MDE 0.05 at n=324 |
| Label quality | blind re-extraction of 20 renderings: precision 0.977, recall 0.992, kappa 0.925 |

## Instrument validation (executed 2026-09-20)

| Check | Result |
|---|---|
| Oracle | 1.000 on every applicable metric, both tasks |
| Null | 0.329 overall_correct (the pass base rate), 0.000 constraint F1 |
| Mock at p=0.9 / p=0.5 | 0.901 / 0.489 overall_correct; pass^5 0.599 (analytic 0.590) |
| Mechanism | paired difference mock 0.9 vs 0.5 excludes zero on every primary metric |
| Errors | 0 of 18,540 graded rows |

## Blockers

- No API credentials in the execution environment, so H0, H1 and H2 have not run.
- The gnosis repository was not reachable by the session's GitHub credential, so G and the ablations have not run.
