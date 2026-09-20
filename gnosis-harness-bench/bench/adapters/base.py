"""Adapter interface shared by every condition.

An adapter turns one bench case into one output dict. It is deliberately thin: the runner
owns retries, timeouts, status classification, grading and persistence. Adapters raise
``AdapterError`` for failures they can recognise (API errors, timeouts, unparseable
output) and let anything else propagate; the runner records those as ``harness_error``.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from bench.schema import RunMeta

FAILURE_CLASSES = ("harness_error", "api_error", "timeout", "unparseable", "model_mismatch", "grader_error")


class AdapterError(Exception):
    """Raised by adapters for failures the runner should classify.

    ``failure_class`` must be one of ``schema.ErrorRow.failure_class``; adapters use
    ``api_error``, ``timeout`` and ``unparseable``.
    """

    def __init__(self, failure_class: str, detail: str = "") -> None:
        if failure_class not in FAILURE_CLASSES:
            raise ValueError(f"unknown failure_class {failure_class!r}")
        super().__init__(f"{failure_class}: {detail}")
        self.failure_class = failure_class
        self.detail = detail


def config_hash(adapter_name: str, config: dict) -> str:
    """Stable short hash of an adapter's class name plus its config dict."""
    payload = json.dumps({"adapter": adapter_name, "config": config}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def empty_output(task: str) -> dict:
    """The output shape with nothing in it (used for refusals and truncations)."""
    if task == "ingestion":
        return {"constraints": []}
    if task == "verdict":
        return {
            "rules_hit": [],
            "overall": "",
            "approval_path": [],
            "recommendation_verb": "",
            "rationale": "",
            "citations": [],
        }
    raise ValueError(f"unknown task {task!r}")


class Adapter:
    """Base class. Subclasses set ``adapter_name`` and implement ``_run``.

    Attributes
    ----------
    name:
        The condition label written into result rows (for example ``mock:p=0.7``).
    config:
        Free-form dict; hashed into ``RunMeta.condition_config_hash``.
    requested_model:
        The model string the adapter asks for, or None for non-model conditions. When set,
        the runner asserts ``RunMeta.model_served == requested_model``.
    """

    adapter_name: str = "base"

    def __init__(self, name: str | None = None, config: dict | None = None) -> None:
        self.config: dict = dict(config or {})
        self.name: str = name or self.adapter_name
        self.requested_model: str | None = None

    # -- public interface -------------------------------------------------------------
    def run(self, case: dict, task: str, rep: int, seed: int) -> tuple[dict, RunMeta, dict]:
        """Return ``(output, meta, trajectory)`` for one case.

        ``output`` matches ``IngestionOutput`` or ``VerdictOutput``. ``meta`` is a
        ``RunMeta``; the runner fills ``attempts`` and may overwrite ``latency_ms``.
        ``trajectory`` is a JSON-serialisable dict with whatever the adapter wants kept
        (request payload, raw response, retrieval ranking, ...).
        """
        t0 = time.perf_counter()
        output, meta_fields, trajectory = self._run(case, task, rep, seed)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        meta = self.make_meta(latency_ms=latency_ms, **meta_fields)
        return output, meta, trajectory

    def _run(self, case: dict, task: str, rep: int, seed: int) -> tuple[dict, dict, dict]:
        raise NotImplementedError

    # -- helpers ----------------------------------------------------------------------
    def make_meta(
        self,
        *,
        latency_ms: float = 0.0,
        model_served: str | None = None,
        stop_reason: str | None = None,
        usage: dict[str, int] | None = None,
        attempts: int = 1,
    ) -> RunMeta:
        return {
            "model_requested": self.requested_model or "",
            "model_served": model_served,
            "stop_reason": stop_reason,
            "usage": dict(usage or {}),
            "latency_ms": float(latency_ms),
            "attempts": attempts,
            "condition_config_hash": config_hash(self.adapter_name, self.config),
        }

    def describe(self) -> dict[str, Any]:
        return {
            "condition": self.name,
            "adapter": self.adapter_name,
            "config": self.config,
            "config_hash": config_hash(self.adapter_name, self.config),
            "requested_model": self.requested_model,
        }
