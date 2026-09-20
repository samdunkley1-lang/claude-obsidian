---
type: meta
title: "Operation Log"
updated: 2026-09-20
tags:
  - meta
  - log
status: evergreen
related:
  - "[[index]]"
  - "[[hot]]"
  - "[[overview]]"
  - "[[sources/_index]]"
---

# Operation Log

Navigation: [[index]] | [[hot]] | [[overview]]

Append-only. New entries go at the TOP. Never edit past entries.

Entry format: `## [YYYY-MM-DD] operation | Title`

Parse recent entries: `grep "^## \[" wiki/log.md | head -10`

---

## [2026-09-20] build | Gnosis Harness Bench (pre-registered harness ablation)
- Type: benchmark build plus instrument validation
- Location: gnosis-harness-bench/ (code, data, pre-registration), wiki/gnosis/gnosis-harness-bench.md
- Built: seeded specs (301 binding rules), reference engine (9 hand-computed tests), 833 engine-asserted scenarios, 94 verified prose renderings, simulation-validated statistics (49 tests), runner and graders (45 tests), reports
- Executed: oracle, null and mock conditions over the full dataset (18,540 rows, 0 errors); blind label audit on 20 renderings (precision 0.977, recall 0.992, kappa 0.925)
- Not executed: live vendor-harness conditions (no API credentials here) and gnosis conditions (gnosis repo not reachable by this session)

## [2026-09-18] research | Gnosis Decision Space and UI Benchmarks
- Type: deep research (seven parallel tracks, one synthesis)
- Location: wiki/gnosis/gnosis-decision-ui-benchmarks.md, wiki/gnosis/_index.md, wiki/sources/gnosis-decision-ui-research.md
- Raw: .raw/gnosis-decision-ui-research/ (7 note files, ~52k words, every figure tagged V/P/I/G)
- Question: what gnosis's decision space and app UI need to be clinical and industry-leading, which metrics to beat, how to make it saleable
- Verdict: tier the decision types around enforcement and behavioural evidence; make the commit record legally complete (MiFID Art 74, Rule 204-2(a)(3), OMS order link, versioned policy); Salt/Carbon-grade UI with two-clock replay and record-then-reveal; publish coverage, retrieval time and replay determinism instead of bps claims; sell AI-governance lineage to the CCO with a trust pack ready before InfoSec
- Caveat: proxy blocked primary-site fetches and search budget was capped; findings rest on snippets and mirrors, re-verify before external use

## [2026-04-08] save | claude-obsidian v1.4 Release Session
- Type: session
- Location: wiki/meta/claude-obsidian-v1.4-release-session.md
- From: full release cycle covering v1.1 (URL/vision/delta tracking, 3 new skills), v1.4.0 (audit response, multi-agent compat, Bases dashboard, em dash scrub, security history rewrite), and v1.4.1 (plugin install command hotfix)
- Key lessons: plugin install is 2-step (marketplace add then install), allowed-tools is not valid frontmatter, Bases uses filters/views/formulas not Dataview syntax, hook context does not survive compaction, git filter-repo needs 2 passes for full scrub

## [2026-04-08] ingest | Claude + Obsidian Ecosystem Research
- Type: research ingest
- Source: `.raw/claude-obsidian-ecosystem-research.md`
- Queries: 6 parallel web searches + 12 repo deep-reads
- Pages created: [[claude-obsidian-ecosystem]], [[cherry-picks]], [[claude-obsidian-ecosystem-research]], [[Ar9av-obsidian-wiki]], [[Nexus-claudesidian-mcp]], [[ballred-obsidian-claude-pkm]], [[rvk7895-llm-knowledge-bases]], [[kepano-obsidian-skills]], [[Claudian-YishenTu]]
- Key finding: 16+ active Claude+Obsidian projects; 13 cherry-pick features identified for v1.3.0+
- Top gap confirmed: no delta tracking, no URL ingestion, no auto-commit

## [2026-04-07] session | Full Audit, System Setup & Plugin Installation
- Type: session
- Location: wiki/meta/full-audit-and-system-setup-session.md
- From: 12-area repo audit, 3 fixes, plugin installed to local system, folder renamed

## [2026-04-07] session | claude-obsidian v1.2.0 Release Session
- Type: session
- Location: wiki/meta/claude-obsidian-v1.2.0-release-session.md
- From: full build session — v1.2.0 plan execution, cosmic-brain→claude-obsidian rename, legal/security audit, branded GIFs, PDF install guide, dual GitHub repos


- Source: `.raw/` (first ingest)
- Pages updated: [[index]], [[log]], [[hot]], [[overview]]
- Key insight: The wiki pattern turns ephemeral AI chat into compounding knowledge — one user dropped token usage by 95%.

## [2026-04-07] setup | Vault initialized

- Plugin: claude-obsidian v1.1.0
- Structure: seed files + first ingest complete
- Skills: wiki, wiki-ingest, wiki-query, wiki-lint, save, autoresearch
