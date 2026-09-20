from __future__ import annotations

import json
from types import SimpleNamespace
from unittest import mock

import pytest

import anthropic
from bench.adapters import build_adapter, parse_condition
from bench.adapters.base import AdapterError
from bench.adapters.claude_common import (
    MODEL_DEFAULT,
    load_system_prompt,
    output_schema,
    parse_json_block,
    policy_semantics_text,
)
from bench.adapters.claude_h0 import ClaudeH0Adapter
from bench.adapters.claude_h1 import ClaudeH1Adapter
from bench.adapters.claude_h2 import BM25, ClaudeH2Adapter, chunk_text, retrieve_chunks, tokenize
from bench.adapters.gnosis_stub import GnosisStubAdapter
from bench.adapters.mock_llm import MockLLMAdapter
from bench.adapters.oracle import OracleAdapter, oracle_output
from bench.cases import constraints_for_case, corpus_for_case
from bench.graders import grade_verdict


# ---------------------------------------------------------------------------------------
# fake SDK objects
# ---------------------------------------------------------------------------------------

def _usage():
    return SimpleNamespace(input_tokens=1200, output_tokens=340, cache_read_input_tokens=0, cache_creation_input_tokens=100)


def fake_tool_response(tool_input: dict, doc_index: int = 0, model: str = MODEL_DEFAULT, stop_reason: str = "tool_use"):
    citation = SimpleNamespace(
        type="char_location", cited_text="No single issuer shall exceed 10% of the Fund's net asset value.",
        document_index=doc_index, document_title=None, start_char_index=10, end_char_index=70,
    )
    text_block = SimpleNamespace(type="text", text="The issuer limit is 10%.", citations=[citation])
    tool_block = SimpleNamespace(type="tool_use", name="record_output", id="toolu_1", input=tool_input)
    return SimpleNamespace(content=[text_block, tool_block], model=model, stop_reason=stop_reason, usage=_usage(), id="msg_1")


def fake_text_response(text: str, stop_reason: str = "end_turn", model: str = MODEL_DEFAULT):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text, citations=None)], model=model, stop_reason=stop_reason, usage=_usage())


@pytest.fixture
def mocked_client():
    with mock.patch("anthropic.Anthropic") as ctor:
        client = mock.MagicMock()
        ctor.return_value = client
        yield ctor, client


# ---------------------------------------------------------------------------------------
# oracle / null / mock
# ---------------------------------------------------------------------------------------

def test_mock_with_p_correct_one_equals_oracle(ingestion_cases, verdict_cases):
    oracle = OracleAdapter()
    mock_adapter = MockLLMAdapter(config={"p_correct": 1.0, "p_ground": 1.0})
    assert mock_adapter.requested_model == "mock"
    for case in ingestion_cases + verdict_cases:
        o_out, o_meta, _ = oracle.run(case, case["task"], 0, 0)
        m_out, m_meta, _ = mock_adapter.run(case, case["task"], 0, 0)
        assert m_out == o_out
        assert m_meta["model_served"] == "mock" == mock_adapter.requested_model
        assert o_meta["model_served"] is None
        assert o_meta["condition_config_hash"] != m_meta["condition_config_hash"]


def test_mock_with_p_correct_zero_is_wrong_and_deterministic(verdict_cases):
    adapter = MockLLMAdapter(name="mock:p=0", config={"p_correct": 0.0, "p_ground": 1.0})
    for case in verdict_cases:
        gold = oracle_output(case, "verdict")
        out1, _, traj1 = adapter.run(case, "verdict", 1, 0)
        out2, _, traj2 = adapter.run(case, "verdict", 1, 0)
        assert out1 == out2 and traj1["cell_seed"] == traj2["cell_seed"]
        assert out1["overall"] != gold["overall"]
        assert out1["recommendation_verb"] != gold["recommendation_verb"]
        # a different rep draws differently seeded noise
        out3, _, traj3 = adapter.run(case, "verdict", 2, 0)
        assert traj3["cell_seed"] != traj1["cell_seed"]


def test_mock_p_ground_zero_fabricates_quotes(verdict_case_by_id):
    case = verdict_case_by_id["GTF-S03-breach"]
    adapter = MockLLMAdapter(config={"p_correct": 1.0, "p_ground": 0.0})
    out, _, _ = adapter.run(case, "verdict", 0, 0)
    g = grade_verdict(out, case, constraints_for_case(case), corpus_for_case(case))
    assert g["overall_correct"] == 1.0
    assert g["citation_grounded"] == 0.0


def test_parse_condition_and_registry():
    assert parse_condition("mock:p=0.7,g=0.9") == ("mock", {"p_correct": 0.7, "p_ground": 0.9})
    assert parse_condition("H2:k=6") == ("H2", {"k": 6})
    a = build_adapter("mock:p=0.7,g=0.9")
    assert a.name == "mock:p=0.7,g=0.9" and a.config["p_correct"] == 0.7
    with pytest.raises(KeyError):
        build_adapter("nope")


def test_gnosis_stub_raises_not_implemented(verdict_cases):
    stub = build_adapter("G-engine")
    assert isinstance(stub, GnosisStubAdapter)
    assert stub.flags["use_policy_engine"] is False and stub.flags["use_validator"] is True
    with pytest.raises(NotImplementedError):
        stub.run(verdict_cases[0], "verdict", 0, 0)
    assert "use_typed_schema" in GnosisStubAdapter.__doc__ and "G-precedent" in GnosisStubAdapter.__doc__


# ---------------------------------------------------------------------------------------
# shared prompt
# ---------------------------------------------------------------------------------------

def test_system_prompt_is_shared_and_restates_policy_semantics(verdict_case_by_id):
    case = verdict_case_by_id["GTF-S02-warn"]
    h0 = ClaudeH0Adapter().build_request(case, "verdict")
    h1 = ClaudeH1Adapter().build_request(case, "verdict")
    h2 = ClaudeH2Adapter().build_request(case, "verdict")
    shared = load_system_prompt("verdict")
    assert h0["system"] == shared
    assert h1["system"][0]["text"] == shared
    assert h2["system"][0]["text"] == shared
    assert policy_semantics_text() in shared
    assert json.dumps(output_schema("verdict"), indent=2) in shared
    assert "verbatim" in shared
    for task in ("ingestion", "verdict"):
        assert chr(0x2014) not in load_system_prompt(task)  # no em dashes anywhere


# ---------------------------------------------------------------------------------------
# H0
# ---------------------------------------------------------------------------------------

def test_h0_json_parsing_fenced_and_unfenced():
    payload = {"overall": "warn", "rules_hit": []}
    assert parse_json_block("Here you go:\n```json\n" + json.dumps(payload) + "\n```\nDone.") == payload
    assert parse_json_block("```\n" + json.dumps(payload) + "\n```") == payload
    assert parse_json_block(json.dumps(payload)) == payload
    assert parse_json_block("Answer: " + json.dumps(payload) + " end") == payload
    with pytest.raises(AdapterError) as exc:
        parse_json_block("no json here at all")
    assert exc.value.failure_class == "unparseable"
    with pytest.raises(AdapterError):
        parse_json_block("")


def test_h0_request_and_parse(mocked_client, verdict_case_by_id):
    ctor, client = mocked_client
    case = verdict_case_by_id["GTF-S02-warn"]
    gold = oracle_output(case, "verdict")
    client.messages.create.return_value = fake_text_response("```json\n" + json.dumps(gold) + "\n```")
    adapter = ClaudeH0Adapter(name="H0")
    out, meta, traj = adapter.run(case, "verdict", 0, 0)
    ctor.assert_called_once_with(max_retries=3, timeout=300.0)
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-opus-5" and kwargs["max_tokens"] == 8000
    assert kwargs["output_config"] == {"effort": "high"}
    for banned in ("thinking", "temperature", "top_p", "fallbacks", "tools", "stream"):
        assert banned not in kwargs
    user = kwargs["messages"][0]["content"]
    assert isinstance(user, str)
    for d in case["documents"]:
        assert f"## Document: {d['rendering_id']}" in user
        assert d["text"].strip() in user
    assert "single fenced JSON block" in user
    assert out == gold
    assert meta["model_served"] == "claude-opus-5" and meta["stop_reason"] == "end_turn"
    assert meta["usage"] == {"input_tokens": 1200, "output_tokens": 340, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 100}
    assert "raw_response" in traj and traj["request"]["model"] == "claude-opus-5"


def test_h0_unparseable_and_truncated(mocked_client, verdict_case_by_id):
    _, client = mocked_client
    case = verdict_case_by_id["GTF-S02-warn"]
    client.messages.create.return_value = fake_text_response("I cannot produce JSON.")
    with pytest.raises(AdapterError) as exc:
        ClaudeH0Adapter().run(case, "verdict", 0, 0)
    assert exc.value.failure_class == "unparseable"
    client.messages.create.return_value = fake_text_response('```json\n{"overall": "wa', stop_reason="max_tokens")
    out, meta, _ = ClaudeH0Adapter().run(case, "verdict", 0, 0)
    assert meta["stop_reason"] == "max_tokens" and out["overall"] == ""


# ---------------------------------------------------------------------------------------
# H1
# ---------------------------------------------------------------------------------------

def _assert_strict_everywhere(schema: dict, path: str = "$") -> None:
    if not isinstance(schema, dict):
        return
    if schema.get("type") == "object":
        assert schema.get("additionalProperties") is False, path
        assert set(schema.get("required", [])) == set(schema.get("properties", {})), path
        for k, v in schema.get("properties", {}).items():
            _assert_strict_everywhere(v, f"{path}.{k}")
    if "items" in schema:
        _assert_strict_everywhere(schema["items"], f"{path}[]")
    for i, alt in enumerate(schema.get("anyOf", [])):
        _assert_strict_everywhere(alt, f"{path}|{i}")


def test_h1_request_construction(mocked_client, verdict_case_by_id):
    ctor, client = mocked_client
    case = verdict_case_by_id["GTF-S02-warn"]
    gold = oracle_output(case, "verdict")
    client.messages.create.return_value = fake_tool_response(gold, doc_index=1)
    adapter = ClaudeH1Adapter(name="H1")
    adapter.run(case, "verdict", 0, 0)
    ctor.assert_called_once_with(max_retries=3, timeout=300.0)
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-opus-5"
    assert kwargs["max_tokens"] == 8000 and kwargs["output_config"] == {"effort": "high"}
    for banned in ("thinking", "temperature", "top_p", "fallbacks", "stream", "betas"):
        assert banned not in kwargs
    assert kwargs["tool_choice"] == {"type": "auto"}
    (tool,) = kwargs["tools"]
    assert tool["name"] == "record_output" and tool["strict"] is True
    assert tool["input_schema"] == output_schema("verdict")
    _assert_strict_everywhere(tool["input_schema"])
    rh = tool["input_schema"]["properties"]["rules_hit"]["items"]["properties"]
    assert set(rh) == {"type", "scope", "verdict", "limit", "exposure_post_trade"}
    cit = tool["input_schema"]["properties"]["citations"]["items"]["properties"]
    assert set(cit) == {"rendering_id", "quote", "claims_constraint"}
    system = kwargs["system"]
    assert system[0]["text"] == load_system_prompt("verdict")
    assert "exactly once" in system[1]["text"]
    content = kwargs["messages"][0]["content"]
    docs = [b for b in content if b["type"] == "document"]
    assert [b["title"] for b in docs] == [d["rendering_id"] for d in case["documents"]]
    for b, d in zip(docs, case["documents"]):
        assert b["citations"] == {"enabled": True}
        assert b["source"] == {"type": "text", "media_type": "text/plain", "data": d["text"]}
    assert content[-1]["type"] == "text" and "As-of date: 2025-03-01" in content[-1]["text"]


def test_h1_response_parsing_harvests_api_citations(verdict_case_by_id):
    case = verdict_case_by_id["GTF-S02-warn"]
    gold = oracle_output(case, "verdict")
    response = fake_tool_response(gold, doc_index=1)
    adapter = ClaudeH1Adapter(name="H1")
    doc_titles = [d["rendering_id"] for d in case["documents"]]
    out, meta, traj = adapter.parse(response, "verdict", doc_titles, {})
    assert out["overall"] == gold["overall"] and out["rules_hit"] == gold["rules_hit"]
    assert len(out["citations"]) == len(gold["citations"]) + 1
    harvested = out["citations"][-1]
    assert harvested["rendering_id"] == "GTF-guidelines-v2-canonical"  # document_index 1 mapped by block order
    assert harvested["quote"].startswith("No single issuer shall exceed 10%")
    assert harvested["start_char"] == 10 and harvested["end_char"] == 70
    assert meta["model_served"] == "claude-opus-5" and meta["stop_reason"] == "tool_use"
    assert meta["usage"]["output_tokens"] == 340
    g = grade_verdict(out, case, constraints_for_case(case), corpus_for_case(case))
    assert g["overall_correct"] == 1.0 and g["citation_grounded"] == 1.0


def test_h1_end_turn_without_tool_is_unparseable(mocked_client, verdict_case_by_id):
    _, client = mocked_client
    case = verdict_case_by_id["GTF-S02-warn"]
    client.messages.create.return_value = fake_text_response("Prose only, no tool call.", stop_reason="end_turn")
    with pytest.raises(AdapterError) as exc:
        ClaudeH1Adapter().run(case, "verdict", 0, 0)
    assert exc.value.failure_class == "unparseable"


def test_h1_refusal_and_truncation_return_empty_output(mocked_client, verdict_case_by_id):
    _, client = mocked_client
    case = verdict_case_by_id["GTF-S02-warn"]
    client.messages.create.return_value = fake_text_response("", stop_reason="refusal")
    out, meta, _ = ClaudeH1Adapter().run(case, "verdict", 0, 0)
    assert meta["stop_reason"] == "refusal" and out["rules_hit"] == [] and out["overall"] == ""
    client.messages.create.return_value = fake_text_response("partial", stop_reason="max_tokens")
    out, meta, _ = ClaudeH1Adapter().run(case, "ingestion" if False else "verdict", 0, 0)
    assert meta["stop_reason"] == "max_tokens" and out["citations"] == []


def test_h1_ingestion_request_uses_ingestion_schema(mocked_client, ingestion_cases):
    _, client = mocked_client
    case = ingestion_cases[0]
    gold = oracle_output(case, "ingestion")
    client.messages.create.return_value = fake_tool_response(gold, doc_index=0)
    out, _, traj = ClaudeH1Adapter().run(case, "ingestion", 0, 0)
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["tools"][0]["input_schema"] == output_schema("ingestion")
    assert out == gold  # harvested citations go to the trajectory, not the ingestion output
    assert traj["harvested_citations"][0]["rendering_id"] == case["rendering_id"]


def test_sdk_errors_map_to_adapter_errors(mocked_client, verdict_case_by_id):
    _, client = mocked_client
    case = verdict_case_by_id["GTF-S02-warn"]
    client.messages.create.side_effect = anthropic.APITimeoutError(request=mock.MagicMock())
    with pytest.raises(AdapterError) as exc:
        ClaudeH1Adapter().run(case, "verdict", 0, 0)
    assert exc.value.failure_class == "timeout"
    client.messages.create.side_effect = anthropic.APIConnectionError(request=mock.MagicMock())
    with pytest.raises(AdapterError) as exc:
        ClaudeH1Adapter().run(case, "verdict", 0, 0)
    assert exc.value.failure_class == "api_error"


def test_no_credentials_is_api_error(monkeypatch, verdict_case_by_id):
    case = verdict_case_by_id["GTF-S02-warn"]
    bare = SimpleNamespace(api_key=None, auth_token=None, credentials=None)
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: bare)
    with pytest.raises(AdapterError) as exc:
        ClaudeH1Adapter().run(case, "verdict", 0, 0)
    assert exc.value.failure_class == "api_error" and "no credentials" in exc.value.detail


# ---------------------------------------------------------------------------------------
# H2
# ---------------------------------------------------------------------------------------

def test_bm25_ranks_chunk_with_query_term_first():
    docs = [
        "The Fund shall maintain cash of at least two percent.",
        "Exposure to the Technology sector shall not exceed thirty five percent.",
        "Schedule A lists Volkov Industrial Holdings and Meridian Tobacco Group.",
    ]
    bm = BM25([tokenize(d) for d in docs])
    assert bm.rank(tokenize("Volkov Industrial"))[0] == 2
    assert bm.rank(tokenize("Technology sector"))[0] == 1
    assert bm.rank(tokenize("cash"))[0] == 0
    assert chunk_text("a\n\nb\n \n\nc") == ["a", "b", "c"]


def test_h2_retrieval_and_title_mapping(mocked_client, verdict_case_by_id):
    _, client = mocked_client
    case = verdict_case_by_id["GTF-S04-hardblock"]
    chunks = retrieve_chunks(case, 3)
    assert len(chunks) == 3
    assert "Volkov Industrial Holdings" in chunks[0]["text"]
    assert chunks[0]["title"] == f"{chunks[0]['rendering_id']}#{chunks[0]['chunk_index']}"

    gold = oracle_output(case, "verdict")
    gold_with_suffix = json.loads(json.dumps(gold))
    gold_with_suffix["citations"][0]["rendering_id"] = "GTF-guidelines-v2-canonical#7"
    client.messages.create.return_value = fake_tool_response(gold_with_suffix, doc_index=0)
    adapter = ClaudeH2Adapter(name="H2", config={"k": 3})
    out, _, traj = adapter.run(case, "verdict", 0, 0)
    kwargs = client.messages.create.call_args.kwargs
    docs = [b for b in kwargs["messages"][0]["content"] if b["type"] == "document"]
    assert len(docs) == 3 and all("#" in b["title"] for b in docs)
    assert docs[0]["citations"] == {"enabled": True}
    assert all(c["rendering_id"] == "GTF-guidelines-v2-canonical" for c in out["citations"])
    assert traj["k"] == 3 and len(traj["retrieval"]) == 3
    assert adapter.map_title("GTF-guidelines-v2-canonical#7") == "GTF-guidelines-v2-canonical"


def test_h2_ingestion_has_no_retrieval(mocked_client, ingestion_cases):
    _, client = mocked_client
    case = ingestion_cases[0]
    client.messages.create.return_value = fake_tool_response(oracle_output(case, "ingestion"))
    ClaudeH2Adapter().run(case, "ingestion", 0, 0)
    docs = [b for b in client.messages.create.call_args.kwargs["messages"][0]["content"] if b["type"] == "document"]
    assert [b["title"] for b in docs] == [case["rendering_id"]]
