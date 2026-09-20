"""Adapter registry: condition name -> (adapter class, base config).

Condition strings on the CLI look like ``name`` or ``name:key=value,key=value``. The
registry key is the part before the colon; the key=value pairs override the base config.
Short aliases ``p`` and ``g`` map to ``p_correct`` and ``p_ground`` for the mock.
"""
from __future__ import annotations

from typing import Any

from bench.adapters.base import Adapter, AdapterError

_ALIASES = {"p": "p_correct", "g": "p_ground"}


def _registry() -> dict[str, tuple[type[Adapter], dict[str, Any]]]:
    # imported lazily so the SDK-dependent adapters do not load for oracle/null/mock runs
    from bench.adapters.claude_h0 import ClaudeH0Adapter
    from bench.adapters.claude_h1 import ClaudeH1Adapter
    from bench.adapters.claude_h2 import ClaudeH2Adapter
    from bench.adapters.gnosis_stub import GnosisStubAdapter
    from bench.adapters.mock_llm import MockLLMAdapter
    from bench.adapters.null import NullAdapter
    from bench.adapters.oracle import OracleAdapter

    return {
        "oracle": (OracleAdapter, {}),
        "null": (NullAdapter, {}),
        "mock": (MockLLMAdapter, {"p_correct": 1.0, "p_ground": 1.0}),
        "H0": (ClaudeH0Adapter, {}),
        "H1": (ClaudeH1Adapter, {}),
        "H2": (ClaudeH2Adapter, {}),
        "G": (GnosisStubAdapter, {"use_typed_schema": True, "use_policy_engine": True, "use_validator": True, "use_precedents": True}),
        "G-schema": (GnosisStubAdapter, {"use_typed_schema": False, "use_policy_engine": True, "use_validator": True, "use_precedents": True}),
        "G-engine": (GnosisStubAdapter, {"use_typed_schema": True, "use_policy_engine": False, "use_validator": True, "use_precedents": True}),
        "G-validator": (GnosisStubAdapter, {"use_typed_schema": True, "use_policy_engine": True, "use_validator": False, "use_precedents": True}),
        "G-precedent": (GnosisStubAdapter, {"use_typed_schema": True, "use_policy_engine": True, "use_validator": True, "use_precedents": False}),
    }


def registry_names() -> list[str]:
    return list(_registry().keys())


def _coerce(value: str) -> Any:
    low = value.strip().lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        if "." in low or "e" in low:
            return float(low)
        return int(low)
    except ValueError:
        return value.strip()


def parse_condition(spec: str) -> tuple[str, dict[str, Any]]:
    """``"mock:p=0.7,g=0.9"`` -> ``("mock", {"p_correct": 0.7, "p_ground": 0.9})``."""
    spec = spec.strip()
    if ":" not in spec:
        return spec, {}
    name, rest = spec.split(":", 1)
    overrides: dict[str, Any] = {}
    for pair in rest.split(","):
        pair = pair.strip()
        if not pair:
            continue
        if "=" not in pair:
            raise ValueError(f"bad condition config {pair!r} in {spec!r}")
        k, v = pair.split("=", 1)
        k = k.strip()
        overrides[_ALIASES.get(k, k)] = _coerce(v)
    return name.strip(), overrides


def build_adapter(spec: str) -> Adapter:
    """Instantiate the adapter for a condition spec; the condition label is the full spec."""
    name, overrides = parse_condition(spec)
    reg = _registry()
    if name not in reg:
        raise KeyError(f"unknown condition {name!r}; known: {sorted(reg)}")
    cls, base = reg[name]
    cfg = dict(base)
    cfg.update(overrides)
    return cls(name=spec, config=cfg)


__all__ = ["Adapter", "AdapterError", "build_adapter", "parse_condition", "registry_names"]
