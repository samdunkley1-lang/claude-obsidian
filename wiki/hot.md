---
type: meta
title: "Hot Cache"
updated: 2026-09-18T00:30:00
tags:
  - meta
  - hot-cache
status: evergreen
related:
  - "[[index]]"
  - "[[log]]"
  - "[[Wiki Map]]"
  - "[[getting-started]]"
  - "[[claude-obsidian-v1.4-release-session]]"
  - "[[gnosis-decision-ui-benchmarks]]"
---

# Recent Context

Navigation: [[index]] | [[log]] | [[overview]]

## Last Updated
2026-09-18: gnosis decision-space and UI deep research filed under wiki/gnosis/

## Gnosis Research (2026-09-18)
Report: [[gnosis-decision-ui-benchmarks]]. Domain index: [[gnosis/_index|Gnosis]]. Raw notes: `.raw/gnosis-decision-ui-research/`.
- **Decision space**: tier the 13 types. Tier 1: valuation marks, liquidity tools, trade allocation, model changes, ESG screens. Tier 2: exits, sizing, corporate-action elections, exceptions. Tier 3: templates.
- **Record completeness**: map the commit schema to MiFID Del Reg 2017/565 Art 74 and Rule 204-2(a)(3), require an OMS order-ID link, version all reference data for replay.
- **UI**: Salt-style medium density, tabular figures, five-state status with glyphs, two labelled replay clocks, frozen maker-checker payloads, record-then-reveal on gated decisions, visible tool trace, WCAG 2.2 AA.
- **Metrics to beat**: publish what nobody publishes (100% sealed coverage, sub-hour retrieval vs SEC 10-to-14-day window, 100% replay hash-match, gate precision). Do not lead with bps-of-alpha claims.
- **Go-to-market**: CCO plus COO at US SEC-registered advisers USD 5-50bn; wedge on AI-governance lineage and IC capture; platform plus modules plus seats, never AUM bps; trust pack (SOC 2, AITEC-AIMA DDQ, DORA Art 30 MSA) before InfoSec.
- **Messaging to strike**: "four eyes required", "AI Act high-risk", the withdrawn SEC PDA proposal, "hallucination-free".
- **Caveat**: snippets and mirrors only; twelve re-verify items at the top of the report.

## Plugin State
- **Version**: 1.4.1 (installed, enabled, user scope)
- **Install ID**: `claude-obsidian@claude-obsidian-marketplace`
- **Releases**: v1.1, v1.4.0, v1.4.1 on GitHub
- **Skills**: 10 (wiki, wiki-ingest, wiki-query, wiki-lint, save, autoresearch, canvas, defuddle, obsidian-bases, obsidian-markdown)
- **Hooks**: 4 (SessionStart, PostCompact, PostToolUse, Stop)
- **Multi-agent**: bootstrap files for Codex, OpenCode, Gemini, Cursor, Windsurf, GitHub Copilot

## Install Command (Correct Two-Step Flow)
```bash
claude plugin marketplace add AgriciDaniel/claude-obsidian
claude plugin install claude-obsidian@claude-obsidian-marketplace
```

There is no `claude plugin install github:owner/repo` shortcut. Both steps are required. Full session note: [[claude-obsidian-v1.4-release-session]].

## Recent Release Cycle (v1.1 → v1.4.1)
- **v1.1**: URL ingestion, vision ingestion, delta tracking manifest, 3 new skills (defuddle, obsidian-bases, obsidian-markdown), multi-depth query modes, PostToolUse auto-commit, removed invalid `allowed-tools` frontmatter field
- **v1.4.0**: Dataview to Bases migration (new `wiki/meta/dashboard.base`), Canvas JSON 1.0 spec completeness, PostCompact hook, Obsidian CLI MCP option, 6 multi-agent bootstrap files, 249 em dashes scrubbed, security git history rewrite to remove placeholder email
- **v1.4.1**: hotfix for wrong plugin install command syntax in README and install-guide.md

## Key Lessons (Recent)
1. Plugin install is always two-step: `marketplace add` then `install plugin@marketplace`
2. `allowed-tools` is NOT valid in skill frontmatter. Use only `name` and `description` (kepano convention).
3. Obsidian Bases uses `filters/views/formulas`, not Dataview `from/where`
4. Canvas edges have asymmetric defaults: `fromEnd="none"`, `toEnd="arrow"`
5. Hook-injected context does not survive compaction. PostCompact hook is required to restore hot cache.
6. `git filter-repo` needs two passes: `--replace-text` for blobs, `--replace-message` for commit messages

## Style Preferences (Saved to Memory)
- **No em dashes** (U+2014) or `--` as punctuation anywhere. Use periods, commas, colons, or parentheses. Hyphens in compound words are fine (auto-commit, multi-agent).
- Keep responses short and direct. No trailing "here's what I did" summaries.
- Parallel tool calls when independent.

## Ecosystem Research (Done 2026-04-08)
16+ Claude + Obsidian projects mapped. Full feature matrix at [[claude-obsidian-ecosystem]]. Prioritized backlog at [[cherry-picks]]. Top competitors: [[Ar9av-obsidian-wiki]] (multi-agent + delta tracking), [[rvk7895-llm-knowledge-bases]] (multi-depth query), [[ballred-obsidian-claude-pkm]] (goal cascade + auto-commit), [[kepano-obsidian-skills]] (authoritative Obsidian skills from Obsidian's own creator).

## Active Threads
- v1.5.0 backlog: `/adopt` command, vault graph analysis in wiki-lint, semantic search via qmd, Marp output
- `community` remote (`avalonreset-pro/claude-obsidian`) still has pre-rewrite history. Force-push needed next time that remote is configured.

## Repo Locations
- Working: `~/Desktop/claude-obsidian/`
- Public: https://github.com/AgriciDaniel/claude-obsidian
- Community (private): https://github.com/avalonreset-pro/claude-obsidian
