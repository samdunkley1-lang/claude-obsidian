---
type: source
title: "Nate Herk — Obsidian + Karpathy Just 10x'd Claude Code Projects"
source_type: transcript
author: "Nate Herk"
date_published: 2026-04-07
url: "https://youtube.com/@nateherk"
confidence: high
key_claims:
  - "LLM wiki makes knowledge compound like interest — nothing is re-derived on every query"
  - "Hot cache (~500 words) enables cross-project context without crawling the full wiki"
  - "One article generates 15-25 wiki pages with full cross-references"
  - "One user dropped token usage by 95% switching from inline context files to a wiki"
  - "Obsidian is the IDE, Claude is the programmer, the wiki is the codebase"
  - "Index file is sufficient at small scale (~100 sources) — no RAG infrastructure needed"
created: 2026-04-07
updated: 2026-04-07
tags:
  - source
  - llm-wiki
  - obsidian
  - karpathy
status: mature
related:
  - "[[LLM Wiki Pattern]]"
  - "[[Hot Cache]]"
  - "[[Compounding Knowledge]]"
  - "[[Andrej Karpathy]]"
  - "[[sources/_index]]"
  - "[[index]]"
sources: []
---

# Nate Herk — Obsidian + Karpathy Just 10x'd Claude Code Projects

**Original:** [Watch on YouTube →](https://youtube.com/@nateherk)
**Credit:** All ideas in this summary belong to Nate Herk and Andrej Karpathy.

> This page is a wiki-style synthesis of the source — an example of what cosmic-brain produces after ingesting a video/transcript. The raw source is not included in the repo.

---

## What This Source Is

Nate Herk demonstrates the [[LLM Wiki Pattern]] in practice using Claude Code and Obsidian. He shows two live vaults: a YouTube transcript archive (36 videos) and a personal second brain. He breaks down [[Andrej Karpathy]]'s original post and walks through a 5-minute setup.

---

## Key Insights

**The wiki compounds.** Normal AI chat is ephemeral — knowledge disappears when the session ends. The wiki pattern changes this: every source ingested, every answer filed back, every connection made persists permanently. See [[Compounding Knowledge]].

**The hot cache is the force multiplier.** A ~500-word file (`wiki/hot.md`) captures what happened recently. New sessions read it first. Cross-project references read it first. It saves crawling dozens of wiki pages just to answer "where were we?" See [[Hot Cache]].

**The stack is intentionally simple.** Claude Code + Obsidian + a folder of markdown files. No vector databases, no embeddings, no infrastructure. The index file alone navigates hundreds of pages.

**Cross-project power.** Other Claude Code projects can reference this vault via their CLAUDE.md. Nate's executive assistant reads from his personal brain vault. Token usage dropped significantly vs inline context files.

**95% token reduction.** One X user turned 383 scattered files and 100+ meeting transcripts into a compact wiki and dropped token usage by 95% when querying with Claude.

**At scale.** The index file alone is sufficient for hundreds of pages. Vector RAG only becomes necessary at millions of documents.

---

## The Live Demo

Nate ingested one article (AI 2027) and Claude produced 23 wiki pages in ~10 minutes:
- 1 source summary
- 6 entity pages (people)
- 5 organization pages
- 1 AI systems page
- Multiple concept pages
- 1 analysis
- Open questions

This is what one ingest looks like when the wiki pattern is applied correctly.

---

## Obsidian as IDE

Obsidian serves as the visual layer. Key features used:
- **Graph view** — see which pages are hubs and which are orphans
- **Backlinks** — follow relationships between pages
- **Dataview** — query pages by frontmatter
- **Web Clipper** — send articles to `.raw/` from any browser in one click

---

## Connections

- [[LLM Wiki Pattern]] — the full architecture this source demonstrates
- [[Compounding Knowledge]] — why the pattern produces increasing returns
- [[Hot Cache]] — the session context mechanism Nate added to his executive assistant vault
- [[Andrej Karpathy]] — originated the LLM wiki pattern that this video explains
