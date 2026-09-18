---
type: source
title: "Gnosis Decision Space and UI Research (raw notes)"
source_type: web-research
created: 2026-09-18
updated: 2026-09-18
tags:
  - gnosis
  - research
  - competitive-analysis
status: current
related:
  - "[[gnosis-decision-ui-benchmarks]]"
  - "[[gnosis/_index]]"
raw_file: ".raw/gnosis-decision-ui-research/"
---

# Source: Gnosis Decision Space and UI Research

**Type**: Web research (seven parallel tracks, search snippets plus GitHub mirrors)
**Date**: 2026-09-18
**Output**: [[gnosis-decision-ui-benchmarks]]

## Summary

Seven research tracks answering three questions: what gnosis's decision space and UI need to be clinical and industry-leading, which comparison metrics to beat, and how to make it saleable. About 52,000 words of raw notes, each finding tagged [V] verified from a cited snippet, [P] primary legal text from prior knowledge, [I] inferred, or [G] guess.

## Evidence Caveat

The session's egress proxy blocked direct fetches of almost every primary site (regulators, vendors, law firms, trade press, academic hosts) and the shared web-search budget was exhausted mid-task in every track. Findings rest on search-result snippets and GitHub mirrors, not full-page reads. Treat every number as "as reported" until re-verified.

## Tracks

| File | Track | Headline |
|---|---|---|
| `decision_taxonomy.md` | Decision types and governance frameworks | 22 decision types; enforcement clusters on valuation, liquidity, allocation, model changes, ESG screens |
| `direct_competitors.md` | Alpha Theory, Essentia, Inalytics, Cabot, Bipsync, AlphaSense, RMS tier, generic DI | No vendor claims pre-decision capture, non-overridable gates, bitemporal replay or precedent matching |
| `incumbent_platforms.md` | Aladdin, Charles River, Bloomberg CMGR, SimCorp, Enfusion, compliance vendors, 2026 copilots, MCP | Four-eyes stops at rule and data changes; MCP FSIG led by Bloomberg |
| `regulatory_requirements.md` | SEC, FINRA, FCA, PRA, MiFID II, DORA, EU AI Act, IOSCO | Art 74 "decision to deal" and 17a-4 audit-trail alternative are the hooks; PDA proposal withdrawn; AI Act Annex III deferred |
| `ui_ux_benchmarks.md` | Salt, Carbon, WCAG 2.2, Core Web Vitals, HAX, PAIR, NIST, automation bias, XTDB | Density tokens, two clocks, cognitive forcing, tool traces |
| `metrics_benchmarks.md` | Decision quality, operations, AI quality, reliability, commercial | Inalytics 49.6% hit rate; Stanford legal-RAG 17 to 33%; SEC 10-to-14-day production window |
| `go_to_market.md` | Buyers, DDQs, DORA Art 30, pricing, wedges, cycles, failure modes | CCO wedge (85% of 411 firms rank AI top priority); trust pack before InfoSec |

## Key Claims

- Regulators penalise the absence of a record binding intent, timing and approver; that tuple is what a sealed commit produces.
- No competitor or incumbent offers typed pre-decision capture with gates, chained approvals, bitemporal replay and precedent matching together.
- The metrics to publish are the ones nobody publishes: sealed coverage, retrieval time, replay hash-match, gate precision.
- Guideline exceptions are a crowded wedge; AI-governance lineage and investment-committee capture are open.
