"""H2: H1 plus a retrieval step for the verdict task.

Each rendering is split into paragraph chunks, chunks are ranked with BM25 (pure Python)
against a query built from the proposal fields and the decision type, and only the top-k
chunks (config ``k``, default 12) are passed as document blocks titled
``<rendering_id>#<chunk_index>``. Citations map back to the rendering id by stripping the
suffix. The ingestion task has one document and no query, so H2 behaves as H1 there.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

from bench.adapters.claude_common import call_messages
from bench.adapters.claude_h1 import ClaudeH1Adapter

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(str(text).lower().replace("_", " "))


def chunk_text(text: str) -> list[str]:
    """Paragraph chunks: blank-line separated, whitespace-stripped, non-empty."""
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.docs = docs
        self.n = len(docs)
        self.avgdl = (sum(len(d) for d in docs) / self.n) if self.n else 0.0
        self.tf = [Counter(d) for d in docs]
        df: Counter = Counter()
        for d in docs:
            df.update(set(d))
        self.idf = {t: math.log(1.0 + (self.n - n_t + 0.5) / (n_t + 0.5)) for t, n_t in df.items()}

    def score(self, query: list[str]) -> list[float]:
        scores = []
        for i, d in enumerate(self.docs):
            dl = len(d)
            s = 0.0
            for t in query:
                if t not in self.tf[i]:
                    continue
                f = self.tf[i][t]
                denom = f + self.k1 * (1.0 - self.b + self.b * dl / (self.avgdl or 1.0))
                s += self.idf.get(t, 0.0) * f * (self.k1 + 1.0) / denom
            scores.append(s)
        return scores

    def rank(self, query: list[str]) -> list[int]:
        scores = self.score(query)
        return sorted(range(self.n), key=lambda i: (-scores[i], i))


def build_query(case: dict) -> list[str]:
    parts = [case.get("decision_type", ""), case.get("fund", "")]
    proposal = case.get("proposal") or {}
    parts.append(str(proposal.get("decision_type", "")))
    for k, v in (proposal.get("fields") or {}).items():
        parts.append(str(k))
        parts.append(str(v))
    return tokenize(" ".join(parts))


def retrieve_chunks(case: dict, k: int) -> list[dict]:
    """Top-k chunks over all supplied renderings, in rank order."""
    units = []
    for d in case["documents"]:
        for idx, chunk in enumerate(chunk_text(d["text"])):
            units.append({"rendering_id": d["rendering_id"], "chunk_index": idx, "text": chunk})
    if not units:
        return []
    bm25 = BM25([tokenize(u["text"]) for u in units])
    query = build_query(case)
    scores = bm25.score(query)
    order = sorted(range(len(units)), key=lambda i: (-scores[i], i))
    chosen = []
    for i in order[: max(0, k)]:
        u = dict(units[i])
        u["score"] = scores[i]
        u["title"] = f"{u['rendering_id']}#{u['chunk_index']}"
        chosen.append(u)
    return chosen


class ClaudeH2Adapter(ClaudeH1Adapter):
    adapter_name = "claude_h2"

    def __init__(self, name: str | None = None, config: dict | None = None) -> None:
        cfg = {"k": 12}
        cfg.update(config or {})
        super().__init__(name, cfg)
        self.k = int(self.config["k"])

    def retrieval(self, case: dict, task: str) -> list[dict]:
        """Ranked chunks for the verdict task; empty for ingestion (no retrieval step)."""
        if task != "verdict":
            return []
        return retrieve_chunks(case, self.k)

    def document_units(self, case: dict, task: str) -> list[tuple[str, str]]:
        if task != "verdict":
            return super().document_units(case, task)
        return [(c["title"], c["text"]) for c in self.retrieval(case, task)]

    def map_title(self, title: str) -> str:
        return title.split("#", 1)[0] if isinstance(title, str) else title

    def _run(self, case: dict, task: str, rep: int, seed: int) -> tuple[dict, dict, dict]:
        chunks = self.retrieval(case, task)
        units = [(c["title"], c["text"]) for c in chunks] if task == "verdict" else None
        req = self.build_request(case, task, units=units)
        doc_titles = [b["title"] for b in req["messages"][0]["content"] if b.get("type") == "document"]
        retrieval = [{k: v for k, v in c.items() if k != "text"} for c in chunks]
        response = call_messages(self.client, **req)
        trajectory: dict[str, Any] = {"request": req, "doc_titles": doc_titles, "retrieval": retrieval, "k": self.k}
        return self.parse(response, task, doc_titles, trajectory)
