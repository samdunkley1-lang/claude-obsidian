"""Shared plumbing for the Claude conditions (H0, H1, H2).

Everything that must be identical across the three harnesses lives here: the system
prompt (rendered from bench/prompts with the policy semantics pasted verbatim), the output
schemas, the client construction and request parameters, and the response bookkeeping.

SDK rules followed here (see the task spec): model default ``claude-opus-5``; no
``thinking`` parameter (adaptive is that model's default); ``output_config.effort = high``;
``max_tokens`` 8000; non-streaming ``client.messages.create``; ``max_retries`` 3;
``timeout`` 300 s; no ``temperature``/``top_p``; no ``fallbacks``.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from bench.adapters.base import Adapter, AdapterError, empty_output
from bench.schema import CONSTRAINT_TYPES

MODEL_DEFAULT = "claude-opus-5"
MAX_TOKENS = 8000
EFFORT = "high"
TIMEOUT_S = 300.0
MAX_RETRIES = 3
TOOL_NAME = "record_output"

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_POLICY_PATH = Path(__file__).resolve().parent.parent / "policy_semantics.md"

SCOPE_LEVELS = ["fund", "sleeve", "issuer", "sector", "country", "rating_bucket"]
COMPARATORS = ["<=", ">=", "between", "prohibited", "required"]
UNITS = ["pct_nav", "years", "rating", "count", "x", "bps", "days", "none"]
VERDICTS = ["pass", "warn", "breach", "hard_block"]
VERBS = ["approve", "hold", "escalate", "request-exception", "reject", "gather-more-data"]


# ---------------------------------------------------------------------------------------
# output schemas (single source for the prompt text and the H1/H2 tool)
# ---------------------------------------------------------------------------------------

def _nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


SCOPE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "level": {"type": "string", "enum": SCOPE_LEVELS},
        "target": _nullable({"type": "string"}),
    },
    "required": ["level", "target"],
    "additionalProperties": False,
}

THRESHOLD_SCHEMA: dict = {
    "anyOf": [
        {"type": "number"},
        {"type": "array", "items": {"type": "number"}},
        {"type": "string"},
        {"type": "null"},
    ]
}

CITATION_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "rendering_id": {"type": "string"},
        "quote": {"type": "string"},
        "claims_constraint": _nullable({"type": "string"}),
    },
    "required": ["rendering_id", "quote", "claims_constraint"],
    "additionalProperties": False,
}

INGESTION_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "constraints": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": list(CONSTRAINT_TYPES)},
                    "scope": SCOPE_SCHEMA,
                    "comparator": {"type": "string", "enum": COMPARATORS},
                    "threshold": THRESHOLD_SCHEMA,
                    "unit": {"type": "string", "enum": UNITS},
                    "effective_from": _nullable({"type": "string"}),
                    "evidence": CITATION_SCHEMA,
                },
                "required": ["type", "scope", "comparator", "threshold", "unit", "effective_from", "evidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["constraints"],
    "additionalProperties": False,
}

VERDICT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "rules_hit": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": list(CONSTRAINT_TYPES)},
                    "scope": SCOPE_SCHEMA,
                    "verdict": {"type": "string", "enum": VERDICTS},
                    "limit": THRESHOLD_SCHEMA,
                    "exposure_post_trade": _nullable({"type": "number"}),
                },
                "required": ["type", "scope", "verdict", "limit", "exposure_post_trade"],
                "additionalProperties": False,
            },
        },
        "overall": {"type": "string", "enum": VERDICTS},
        "approval_path": {"type": "array", "items": {"type": "string"}},
        "recommendation_verb": {"type": "string", "enum": VERBS},
        "rationale": {"type": "string"},
        "citations": {"type": "array", "items": CITATION_SCHEMA},
    },
    "required": ["rules_hit", "overall", "approval_path", "recommendation_verb", "rationale", "citations"],
    "additionalProperties": False,
}


def output_schema(task: str) -> dict:
    if task == "ingestion":
        return INGESTION_SCHEMA
    if task == "verdict":
        return VERDICT_SCHEMA
    raise ValueError(f"unknown task {task!r}")


def record_output_tool(task: str) -> dict:
    return {
        "name": TOOL_NAME,
        "description": "Record the final structured answer. Call it exactly once with the complete output.",
        "strict": True,
        "input_schema": output_schema(task),
    }


# ---------------------------------------------------------------------------------------
# prompts
# ---------------------------------------------------------------------------------------

def policy_semantics_text() -> str:
    return _POLICY_PATH.read_text(encoding="utf-8").strip()


def load_system_prompt(task: str) -> str:
    """The shared system prompt: identical for H0, H1 and H2."""
    path = _PROMPTS_DIR / f"system_{task}.md"
    template = path.read_text(encoding="utf-8")
    text = template.replace("{{POLICY_SEMANTICS}}", policy_semantics_text())
    text = text.replace("{{OUTPUT_SCHEMA}}", json.dumps(output_schema(task), indent=2))
    return text.strip()


def task_block(case: dict, task: str) -> str:
    """The per-case instructions (identical wording across harnesses)."""
    if task == "ingestion":
        return (
            f"Extract every binding constraint from the document with rendering_id "
            f"\"{case['rendering_id']}\" supplied above. Use exactly that rendering_id in every "
            f"evidence entry and quote the sentence that states each limit verbatim."
        )
    docs = ", ".join(d["rendering_id"] for d in case["documents"])
    return "\n".join(
        [
            f"Fund: {case['fund']}",
            f"Decision type: {case['decision_type']}",
            f"As-of date: {case['as_of']}",
            f"Supplied documents (rendering ids): {docs}",
            "Proposal (JSON):",
            json.dumps(case["proposal"], indent=2, sort_keys=True),
            "Portfolio state (JSON):",
            json.dumps(case["portfolio"], indent=2, sort_keys=True),
            "Evaluate the proposal against the document version in force at the as-of date.",
        ]
    )


def case_documents(case: dict, task: str) -> list[tuple[str, str]]:
    """(rendering_id, text) pairs the harness must present."""
    if task == "ingestion":
        return [(case["rendering_id"], case["text"])]
    return [(d["rendering_id"], d["text"]) for d in case["documents"]]


# ---------------------------------------------------------------------------------------
# client and response helpers
# ---------------------------------------------------------------------------------------

def make_client() -> Any:
    """Construct the SDK client; AdapterError('api_error', 'no credentials') if none resolve."""
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover
        raise AdapterError("harness_error", f"anthropic SDK not installed: {exc}") from exc
    try:
        client = anthropic.Anthropic(max_retries=MAX_RETRIES, timeout=TIMEOUT_S)
    except Exception as exc:
        raise AdapterError("api_error", f"no credentials: {exc}") from exc
    has_cred = any(getattr(client, attr, None) for attr in ("api_key", "auth_token", "credentials"))
    if not has_cred and not _looks_mocked(client):
        raise AdapterError("api_error", "no credentials")
    return client


def _looks_mocked(client: Any) -> bool:
    mod = type(client).__module__ or ""
    return mod.startswith("unittest.mock") or mod.startswith("mock")


def call_messages(client: Any, **kwargs: Any) -> Any:
    """``client.messages.create`` with SDK exceptions mapped onto AdapterError classes."""
    import anthropic

    try:
        return client.messages.create(**kwargs)
    except anthropic.APITimeoutError as exc:
        raise AdapterError("timeout", str(exc)) from exc
    except (anthropic.AuthenticationError, anthropic.CredentialsError) as exc:
        raise AdapterError("api_error", f"no credentials: {exc}") from exc
    except anthropic.APIConnectionError as exc:
        raise AdapterError("api_error", f"connection: {exc}") from exc
    except anthropic.APIStatusError as exc:
        raise AdapterError("api_error", f"{type(exc).__name__}: {exc}") from exc
    except anthropic.AnthropicError as exc:
        raise AdapterError("api_error", f"{type(exc).__name__}: {exc}") from exc
    except TypeError as exc:
        if "authentication" in str(exc).lower():
            raise AdapterError("api_error", f"no credentials: {exc}") from exc
        raise


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def usage_dict(response: Any) -> dict[str, int]:
    usage = _get(response, "usage")
    out: dict[str, int] = {}
    for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
        v = _get(usage, k) if usage is not None else None
        out[k] = int(v) if isinstance(v, (int, float)) else 0
    return out


def response_meta(response: Any) -> dict[str, Any]:
    return {
        "model_served": _get(response, "model"),
        "stop_reason": _get(response, "stop_reason"),
        "usage": usage_dict(response),
    }


def response_dump(response: Any) -> Any:
    """A JSON-friendly copy of the raw response for the trajectory."""
    for attr in ("model_dump", "to_dict"):
        fn = getattr(response, attr, None)
        if callable(fn):
            try:
                return _jsonable(fn())
            except Exception:
                pass
    return _jsonable(response)


def _jsonable(x: Any, depth: int = 0) -> Any:
    if depth > 8:
        return str(x)
    if isinstance(x, (str, int, float, bool)) or x is None:
        return x
    if isinstance(x, dict):
        return {str(k): _jsonable(v, depth + 1) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v, depth + 1) for v in x]
    d = getattr(x, "__dict__", None)
    if isinstance(d, dict):
        return {k: _jsonable(v, depth + 1) for k, v in d.items() if not k.startswith("_")}
    return str(x)


def text_of(response: Any) -> str:
    parts = []
    for block in _get(response, "content", []) or []:
        if _get(block, "type") == "text":
            parts.append(_get(block, "text", "") or "")
    return "".join(parts)


def harvest_citations(response: Any, doc_titles: list[str], map_title=None) -> list[dict]:
    """API citations from every text block, mapped back to rendering ids.

    ``doc_titles`` is the ordered list of document-block titles as sent, so
    ``document_index`` can be resolved even when ``document_title`` is missing.
    """
    out: list[dict] = []
    for block in _get(response, "content", []) or []:
        if _get(block, "type") != "text":
            continue
        for cit in _get(block, "citations", None) or []:
            cited = _get(cit, "cited_text")
            if not cited:
                continue
            idx = _get(cit, "document_index")
            title = _get(cit, "document_title")
            if not title and isinstance(idx, int) and 0 <= idx < len(doc_titles):
                title = doc_titles[idx]
            if not title:
                continue
            rid = map_title(title) if map_title else title
            entry: dict[str, Any] = {"rendering_id": rid, "quote": cited, "claims_constraint": None, "source": "api_citation"}
            if _get(cit, "type") == "char_location":
                s, e = _get(cit, "start_char_index"), _get(cit, "end_char_index")
                if isinstance(s, int):
                    entry["start_char"] = s
                if isinstance(e, int):
                    entry["end_char"] = e
            out.append(entry)
    return out


def coerce_output(raw: Any, task: str) -> dict:
    """Fill in missing top-level keys so graders always see the full shape."""
    base = empty_output(task)
    if isinstance(raw, dict):
        for k in base:
            if k in raw:
                base[k] = raw[k]
    return base


_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.S)


def parse_json_block(text: str) -> dict:
    """Parse the model's JSON answer: fenced block preferred, then bare JSON, then the
    outermost brace span. Raises AdapterError('unparseable') when nothing parses."""
    if not isinstance(text, str) or not text.strip():
        raise AdapterError("unparseable", "empty response text")
    candidates: list[str] = []
    fenced = _FENCE_RE.findall(text)
    candidates.extend(f.strip() for f in reversed(fenced))
    candidates.append(text.strip())
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    for cand in candidates:
        try:
            obj = json.loads(cand)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    raise AdapterError("unparseable", f"no JSON object found in response: {text[:200]!r}")


class ClaudeAdapterBase(Adapter):
    """Common config handling for the three Claude harnesses."""

    adapter_name = "claude"

    def __init__(self, name: str | None = None, config: dict | None = None) -> None:
        cfg = {"model": MODEL_DEFAULT, "effort": EFFORT, "max_tokens": MAX_TOKENS}
        cfg.update(config or {})
        super().__init__(name, cfg)
        self.requested_model = str(self.config["model"])
        self._client: Any = None

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = make_client()
        return self._client

    def base_request(self, task: str) -> dict[str, Any]:
        return {
            "model": self.requested_model,
            "max_tokens": int(self.config["max_tokens"]),
            "output_config": {"effort": str(self.config["effort"])},
        }

    def finish(self, output: dict, response: Any, trajectory: dict) -> tuple[dict, dict, dict]:
        meta = response_meta(response)
        trajectory["raw_response"] = response_dump(response)
        return output, meta, trajectory
