---
type: meta
title: "Hot Cache"
updated: 2026-08-18T00:00:00
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
  - "[[gnosis-app-review-handoff]]"
---

# Recent Context

Navigation: [[index]] | [[log]] | [[overview]]

## Last Updated
2026-08-18: gnosis-app review requested but blocked on repo access; handoff filed

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

## gnosis (separate product, separate repo)
- Codebase is **`hobsynth/gnosis-app`** (private), not this vault. This repo holds only the strategy note [[Can g-Nosis be a personal mind]] on branch `claude/gnosis-personal-assistant-idea-4fkgff`.
- Chris Hobson (`chrisafhobson@gmail.com`) is the other developer. Latest commit `587a2a2b` "fix(desktop): select-all takes up to thirty facts" (19 Aug 2026).
- A cloud session sourced from `samdunkley1-lang/*` **cannot** reach it: cross-tier `add_repo` is refused, anonymous clone fails (private), GitHub MCP is scoped out. Start a session with `hobsynth/gnosis-app` as the initial source instead. Full trace: [[gnosis-app-review-handoff]].

## Active Threads
- v1.5.0 backlog: `/adopt` command, vault graph analysis in wiki-lint, semantic search via qmd, Marp output
- `community` remote (`avalonreset-pro/claude-obsidian`) still has pre-rewrite history. Force-push needed next time that remote is configured.

## Repo Locations
- Working: `~/Desktop/claude-obsidian/`
- gnosis app (different product): https://github.com/hobsynth/gnosis-app (private)
- Public: https://github.com/AgriciDaniel/claude-obsidian
- Community (private): https://github.com/avalonreset-pro/claude-obsidian
