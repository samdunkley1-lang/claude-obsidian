"""H0: the bare model.

Every document is pasted as plain text inside one user message under a header, the shared
system prompt is sent as the system, and the model is asked to answer with a single fenced
JSON block matching the output schema. The JSON is parsed from the text; a parse failure
is ``AdapterError("unparseable")``.
"""
from __future__ import annotations

from typing import Any

from bench.adapters.base import AdapterError, empty_output
from bench.adapters.claude_common import (
    ClaudeAdapterBase,
    call_messages,
    case_documents,
    coerce_output,
    load_system_prompt,
    parse_json_block,
    task_block,
    text_of,
)


def build_user_message(case: dict, task: str) -> str:
    parts = ["# Documents", ""]
    for rid, text in case_documents(case, task):
        parts += [f"## Document: {rid}", "", text.strip(), ""]
    parts += ["# Task", "", task_block(case, task), ""]
    parts.append(
        "Answer with a single fenced JSON block (```json ... ```) that matches the output schema "
        "in the system prompt, and nothing else after the block."
    )
    return "\n".join(parts)


class ClaudeH0Adapter(ClaudeAdapterBase):
    adapter_name = "claude_h0"

    def build_request(self, case: dict, task: str) -> dict[str, Any]:
        req = self.base_request(task)
        req["system"] = load_system_prompt(task)
        req["messages"] = [{"role": "user", "content": build_user_message(case, task)}]
        return req

    def _run(self, case: dict, task: str, rep: int, seed: int) -> tuple[dict, dict, dict]:
        req = self.build_request(case, task)
        response = call_messages(self.client, **req)
        trajectory: dict[str, Any] = {"request": req}
        return self.parse(response, task, trajectory)

    def parse(self, response: Any, task: str, trajectory: dict) -> tuple[dict, dict, dict]:
        stop = getattr(response, "stop_reason", None)
        text = text_of(response)
        trajectory["response_text"] = text
        if stop == "refusal":
            return self.finish(empty_output(task), response, trajectory)
        try:
            raw = parse_json_block(text)
        except AdapterError:
            if stop == "max_tokens":
                return self.finish(empty_output(task), response, trajectory)
            raise
        return self.finish(coerce_output(raw, task), response, trajectory)
