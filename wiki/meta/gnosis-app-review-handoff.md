---
type: session
title: "gnosis-app Codebase Review: Access Trace and Handoff"
created: 2026-08-18
updated: 2026-08-18
tags:
  - meta
  - session
  - gnosis
  - handoff
  - blocked
status: current
related:
  - "[[Can g-Nosis be a personal mind]]"
  - "[[index]]"
  - "[[log]]"
  - "[[hot]]"
sources: []
---

# gnosis-app Codebase Review: Access Trace and Handoff

A requested review of Chris Hobson's latest branch on the gnosis codebase, compared against roadmap and forward-planning documents, could not be executed from this session. This note records where the codebase lives, how that was established, why the session could not reach it, and the exact brief to re-run elsewhere.

## Request

Pull down Chris's latest branch, clone locally, scan the codebase, compare it to any roadmap or future-delivery planning documents, and advise on what remains to be built to make the product industry leading. Constraint: no reliance on prior knowledge of gnosis. Every fact had to be established from reachable sources.

## Where the codebase actually lives

**`hobsynth/gnosis-app`** (private). Established from three independent traces, none of them prior knowledge:

1. **Session history.** Sessions titled "Write API e2e tests feat/firm-up", "Build Playwright e2e tests" and "Refresh the stale RLS coverage ratchet" all carry `hobsynth/gnosis-app` as their git source, on branches `feature/e2e-testing`, `claude/beautiful-banach-bc995d` and `claude/gracious-hawking-da2e01`.
2. **An explicit prior blocker.** Session "End-user unit testing setup" (2026-07-21) ended needing input, with the recorded action: "Grant GitHub app access to `hobsynth/gnosis-app` and start a session on it". The same wall was hit then.
3. **The `/dogfooding` skill on disk** (`~/.claude/skills/synced/dogfooding/SKILL.md`), which describes the system in detail and is the richest de-facto specification available without repo access.

## Who Chris is

**Chris Hobson** (`chrisafhobson@gmail.com`). Latest commit at time of writing: `587a2a2b` "fix(desktop): select-all takes up to thirty facts" (19 Aug 2026). Confirmed by the user, not discoverable from any reachable repo.

Prior sessions referencing his work: "Set up Chris's branch to test login locally", "Test Chris's e2e intake plan locally", "Check Chris commits today", "Review open PRs and plan cleanup with Chris".

## Why this session could not reach it

Three independent routes were tried and all closed:

| Route | Result |
|-------|--------|
| `add_repo hobsynth/gnosis-app` | Refused: "cross-tier adds are not supported in v1". The session is pinned to owner `samdunkley1-lang`. |
| Anonymous clone via the git proxy | `fatal: could not read Username for 'https://github.com'`. The repo is private, and the proxy serves anonymous reads of public repos only. |
| GitHub MCP (`get_file_contents`) | "Access denied: repository is not configured for this session. Allowed repositories: samdunkley1-lang/claude-obsidian". |

This is a session-scope limit rather than a missing permission. The fix is to start a session with `hobsynth/gnosis-app` as the **initial source**, not to grant something to this one.

## What this repo does contain

`samdunkley1-lang/claude-obsidian` is a fork of `AgriciDaniel/claude-obsidian`, an Obsidian wiki plugin. It is unrelated to the gnosis application beyond one strategy note.

- Fork sits at **v1.4.3**; upstream has since reached **v2.1.0** (native Windows compatibility, Windows CI matrix, WSL troubleshooting guide, audited release manifests). The fork is roughly four minor versions behind.
- No commit, branch, file or contributor named Chris exists anywhere in the fork or upstream.
- Branch `claude/gnosis-personal-assistant-idea-4fkgff` carries a single note, [[Can g-Nosis be a personal mind]], a five-seat council verdict on reframing g-Nosis as a personal decision journal. Strategy only, no code.

## What the dogfooding skill reveals about the system

Useful as a starting map for whoever runs the real review. All of it is asserted by the skill, none of it verified against source:

- **Stack**: Next.js app, 8 SQLite databases (`securities_master`, `portfolio_oms`, `index_benchmark`, `compliance_mandate`, `corporate_actions`, `decision_ledger`, `oms_trading`, `explore_nodes`), `decision_ledger` at 21+ migrations, optional Neo4j, `mcp-server.mjs` exposing 22 read tools, `/api/stream` chat agent.
- **Core loop**: a 7-phase decision lifecycle (propose, capture, evaluate, exception, approve, link-precedent, commit) written as events, with bitemporal replay via `getDecisionAtTime`.
- **Precedent engine**: 5 matchers (structural, trace-pattern, graph-embedding, hybrid, semantic). Trace-pattern (n-gram Jaccard over event-chain shape) is called out as gnosis-unique.
- **Regulatory surface**: hard gates (info-barrier, conflict-of-interest) that admins cannot author or override, maker-checker on decision type versioning, sealed-on-commit immutability, a recommendation validator banning causal verbs and unbound IDs.
- **Explicitly unfinished**: the learning loop is hard-gated to "always reject candidate weights until a regulated replay harness is built". That is a named, self-declared gap and an obvious first entry on any remaining-work list.
- **Fixture**: Midland Capital, 5 funds (GTF, EIF, DGF, CBF, EMF), 5 PMs and a CIO, with three demo arcs (NVDA single-name overweight, duration extension, TCOR acquisition election).
- **Expected planning artefacts** to compare against: `docs/dogfood/README.md` and its coverage table, `docs/dogfood/sessions/`, `tasks/lessons.md`, `CLAUDE.md`.

## Brief to re-run

Start a session with `hobsynth/gnosis-app` as the initial source, check out Chris Hobson's latest branch containing `587a2a2b`, then:

1. Scan the codebase and inventory what is actually built versus scaffolded versus stubbed.
2. Locate every roadmap and forward-planning document, including `docs/dogfood/README.md`, `tasks/`, `CLAUDE.md`, `DESIGN.md` files, and any brief the repo carries.
3. Diff intent against implementation, calling out the self-declared gaps first (the hard-gated learning loop, the regulated replay harness).
4. Advise on remaining work to reach industry-leading, separating table stakes from genuine differentiation.

Cross-reference [[Can g-Nosis be a personal mind]] when weighing which gaps matter: the council's finding was that the sealed immutable ledger and bitemporal anti-hindsight replay carry the differentiation, and that governance machinery built for multi-party institutions does not transfer to a single user.
