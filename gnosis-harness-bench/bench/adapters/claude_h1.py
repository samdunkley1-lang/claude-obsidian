"""H1: the fair vendor harness.

Documents are passed as ``document`` content blocks (text source, title = rendering_id)
with citations enabled. One strict tool, ``record_output``, whose input schema is the
task's output schema, is offered with ``tool_choice: auto`` and a system instruction to
call it exactly once. The tool input is the output; API citations found on text blocks are
harvested and appended to the citations with the rendering id resolved from the document
block order.
"""
from __future__ import annotations

from typing import Any

from bench.adapters.base import AdapterError, empty_output
from bench.adapters.claude_common import (
    TOOL_NAME,
    ClaudeAdapterBase,
    call_messages,
    case_documents,
    coerce_output,
    harvest_citations,
    load_system_prompt,
    record_output_tool,
    task_block,
)

TOOL_INSTRUCTION = (
    f"Call the `{TOOL_NAME}` tool exactly once with your complete answer. Do not answer in prose "
    "instead of the tool call. You may write brief reasoning with citations before the call."
)


def document_block(title: str, text: str) -> dict:
    return {
        "type": "document",
        "source": {"type": "text", "media_type": "text/plain", "data": text},
        "title": title,
        "citations": {"enabled": True},
    }


class ClaudeH1Adapter(ClaudeAdapterBase):
    adapter_name = "claude_h1"

    # ---- request ------------------------------------------------------------------
    def document_units(self, case: dict, task: str) -> list[tuple[str, str]]:
        """(title, text) pairs to send as document blocks. H2 overrides this."""
        return case_documents(case, task)

    def map_title(self, title: str) -> str:
        """Document title -> rendering_id. H2 strips its chunk suffix here."""
        return title

    def build_request(self, case: dict, task: str, units: list[tuple[str, str]] | None = None) -> dict[str, Any]:
        if units is None:
            units = self.document_units(case, task)
        content: list[dict] = [document_block(title, text) for title, text in units]
        content.append({"type": "text", "text": task_block(case, task)})
        req = self.base_request(task)
        req["system"] = [
            {"type": "text", "text": load_system_prompt(task)},
            {"type": "text", "text": TOOL_INSTRUCTION},
        ]
        req["messages"] = [{"role": "user", "content": content}]
        req["tools"] = [record_output_tool(task)]
        req["tool_choice"] = {"type": "auto"}
        return req

    def _run(self, case: dict, task: str, rep: int, seed: int) -> tuple[dict, dict, dict]:
        req = self.build_request(case, task)
        doc_titles = [b["title"] for b in req["messages"][0]["content"] if b.get("type") == "document"]
        response = call_messages(self.client, **req)
        trajectory: dict[str, Any] = {"request": req, "doc_titles": doc_titles}
        return self.parse(response, task, doc_titles, trajectory)

    # ---- response -----------------------------------------------------------------
    def parse(self, response: Any, task: str, doc_titles: list[str], trajectory: dict) -> tuple[dict, dict, dict]:
        stop = getattr(response, "stop_reason", None)
        tool_input = None
        for block in getattr(response, "content", None) or []:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == TOOL_NAME:
                tool_input = getattr(block, "input", None)
                if isinstance(tool_input, str):
                    import json

                    try:
                        tool_input = json.loads(tool_input)
                    except json.JSONDecodeError as exc:
                        raise AdapterError("unparseable", f"tool input is not JSON: {exc}") from exc
        harvested = harvest_citations(response, doc_titles, self.map_title)
        trajectory["harvested_citations"] = harvested
        if stop == "refusal":
            return self.finish(empty_output(task), response, trajectory)
        if not isinstance(tool_input, dict):
            if stop == "max_tokens":
                return self.finish(empty_output(task), response, trajectory)
            raise AdapterError("unparseable", f"no {TOOL_NAME} tool_use block (stop_reason={stop})")
        output = coerce_output(tool_input, task)
        output = self.normalise_ids(output, task)
        if task == "verdict":
            cits = list(output.get("citations") or [])
            cits.extend({k: v for k, v in h.items() if k != "source"} for h in harvested)
            output["citations"] = cits
        return self.finish(output, response, trajectory)

    def normalise_ids(self, output: dict, task: str) -> dict:
        """Map rendering ids in the tool output back through ``map_title``."""
        if task == "verdict":
            for c in output.get("citations") or []:
                if isinstance(c, dict) and isinstance(c.get("rendering_id"), str):
                    c["rendering_id"] = self.map_title(c["rendering_id"])
        else:
            for c in output.get("constraints") or []:
                ev = c.get("evidence") if isinstance(c, dict) else None
                if isinstance(ev, dict) and isinstance(ev.get("rendering_id"), str):
                    ev["rendering_id"] = self.map_title(ev["rendering_id"])
        return output
