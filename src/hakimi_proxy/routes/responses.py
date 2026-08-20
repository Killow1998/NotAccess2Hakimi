"""Responses API facade over the existing Chat Completions route."""

from __future__ import annotations

import json
import time
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from hakimi_proxy.routes.chat import _run_chat_completion

router = APIRouter()

_CUSTOM_TOOL_PARAMETERS = {
    "type": "object",
    "properties": {"input": {"type": "string"}},
    "required": ["input"],
    "additionalProperties": False,
}


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict) and item.get("type") in {"input_text", "output_text", "text"}:
            parts.append(str(item.get("text", "")))
    return "".join(parts)


def _chat_content(content: Any) -> str | list[dict[str, Any]]:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[dict[str, Any]] = []
    text_only: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append({"type": "text", "text": item})
            text_only.append(item)
            continue
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type in {"input_text", "output_text", "text"}:
            text = str(item.get("text", ""))
            parts.append({"type": "text", "text": text})
            text_only.append(text)
        elif item_type in {"input_image", "image_url"}:
            image_url = item.get("image_url", "")
            if isinstance(image_url, dict):
                image_url = image_url.get("url", "")
            if image_url:
                parts.append({"type": "image_url", "image_url": {"url": image_url}})
    return "".join(text_only) if len(parts) == len(text_only) else parts


def _custom_tool_arguments(value: Any) -> str:
    """Represent a Responses custom-tool input as a Chat tool-call payload."""
    if isinstance(value, str):
        return json.dumps({"input": value}, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, dict):
        return json.dumps({"input": value}, ensure_ascii=False, separators=(",", ":"))
    return json.dumps({"input": str(value)}, ensure_ascii=False, separators=(",", ":"))


def _custom_tool_input(arguments: Any) -> str:
    """Recover the raw Responses custom-tool input from Chat arguments."""
    if isinstance(arguments, dict):
        value = arguments.get("input", arguments)
        return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if not isinstance(arguments, str):
        return str(arguments)
    try:
        value = json.loads(arguments)
    except json.JSONDecodeError:
        return arguments
    if isinstance(value, dict) and "input" in value:
        value = value["input"]
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _thought_signature_extra(value: Any) -> dict[str, Any] | None:
    """Keep the AGY thought signature on a tool call across Responses turns."""
    if not isinstance(value, dict):
        return None
    extra = value.get("extra_content")
    if not isinstance(extra, dict):
        return None
    google = extra.get("google")
    signature = google.get("thought_signature") if isinstance(google, dict) else None
    if not isinstance(signature, str) or not signature:
        return None
    return {"google": {"thought_signature": signature}}


def _thought_signature(value: Any) -> str:
    extra = _thought_signature_extra(value)
    if not extra:
        return ""
    return extra["google"]["thought_signature"]


def _thought_signatures(value: Any) -> list[str]:
    signatures: list[str] = []
    direct = _thought_signature(value)
    if direct:
        signatures.append(direct)
    if isinstance(value, dict):
        for signature in value.get("na2h_thought_signatures", []):
            if isinstance(signature, str) and signature and signature not in signatures:
                signatures.append(signature)
    return signatures


def _reasoning_signature(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    signature = value.get("encrypted_content")
    return signature.strip() if isinstance(signature, str) else ""


def _reasoning_item(signature: str, summary: str = "") -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": "rs_" + uuid4().hex,
        "type": "reasoning",
        "status": "completed",
        "encrypted_content": signature,
        "summary": [],
    }
    if summary:
        item["summary"] = [{"type": "summary_text", "text": summary}]
    return item


def _raw_tools(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Collect regular and Codex additional-tools declarations."""
    collected: list[dict[str, Any]] = []

    def visit(items: Any) -> None:
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "namespace":
                visit(item.get("tools"))
            elif item.get("type") in {"function", "custom"}:
                collected.append(item)

    visit(body.get("tools"))
    source = body.get("input")
    if isinstance(source, dict):
        source = [source]
    if isinstance(source, list):
        for item in source:
            if isinstance(item, dict) and item.get("type") == "additional_tools":
                visit(item.get("tools"))
    return collected


def _tool_registry(body: dict[str, Any]) -> tuple[list[dict[str, Any]], set[str]]:
    tools: list[dict[str, Any]] = []
    custom_names: set[str] = set()
    seen: set[str] = set()
    for item in _raw_tools(body):
        kind = item.get("type")
        function = item.get("function", item)
        name = function.get("name")
        if not isinstance(name, str) or not name or name in seen:
            continue
        seen.add(name)
        if kind == "custom":
            custom_names.add(name)
            parameters = dict(_CUSTOM_TOOL_PARAMETERS)
        else:
            parameters = function.get("parameters") or {"type": "object"}
        tools.append({
            "type": "function",
            "function": {
                "name": name,
                "description": function.get("description", ""),
                "parameters": parameters,
            },
        })
    return tools, custom_names


def _messages(body: dict[str, Any]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    instructions = body.get("instructions")
    if instructions:
        messages.append({"role": "system", "content": _content_text(instructions)})

    source = body.get("input", "")
    if isinstance(source, str):
        return messages + [{"role": "user", "content": source}]
    if isinstance(source, dict):
        source = [source]
    if not isinstance(source, list):
        return messages

    pending_calls: list[dict[str, Any]] = []
    call_order: list[str] = []
    pending_outputs: list[dict[str, Any]] = []
    pending_signatures: list[str] = []

    def flush_calls() -> None:
        if pending_calls:
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": list(pending_calls),
            })
            pending_calls.clear()

    def flush_outputs() -> None:
        if not pending_outputs:
            return
        flush_calls()
        by_id = {
            item.get("call_id", ""): item
            for item in pending_outputs
            if item.get("call_id")
        }
        ordered = [by_id[call_id] for call_id in call_order if call_id in by_id]
        ordered_ids = {item.get("call_id") for item in ordered}
        ordered.extend(item for item in pending_outputs if item.get("call_id") not in ordered_ids)
        for item in ordered:
            messages.append({
                "role": "tool",
                "tool_call_id": item.get("call_id", ""),
                "content": _content_text(item.get("output", "")),
            })
        pending_outputs.clear()
        call_order.clear()

    def attach_signature(call: dict[str, Any], signature: str) -> None:
        if signature and "extra_content" not in call:
            call["extra_content"] = {"google": {"thought_signature": signature}}

    for index, item in enumerate(source):
        if not isinstance(item, dict):
            continue
        item_type = item.get("type", "message")
        if item_type == "message":
            flush_outputs()
            flush_calls()
            messages.append({
                "role": item.get("role", "user"),
                "content": _chat_content(item.get("content", "")),
            })
        elif item_type == "reasoning":
            signature = _reasoning_signature(item)
            if not signature:
                continue
            next_type = ""
            for next_item in source[index + 1:]:
                if not isinstance(next_item, dict):
                    continue
                candidate_type = next_item.get("type", "message")
                if candidate_type == "additional_tools":
                    continue
                next_type = candidate_type
                break
            if next_type in {"function_call", "custom_tool_call"} or not pending_calls:
                pending_signatures.append(signature)
            else:
                attach_signature(pending_calls[-1], signature)
        elif item_type == "custom_tool_call":
            if pending_outputs:
                flush_outputs()
            call_id = item.get("call_id") or item.get("id") or "custom-tool-call"
            call = {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": item.get("name", "tool"),
                    "arguments": _custom_tool_arguments(item.get("input", "")),
                },
            }
            if pending_signatures:
                attach_signature(call, pending_signatures.pop(0))
            if extra := _thought_signature_extra(item):
                call["extra_content"] = extra
            pending_calls.append(call)
            call_order.append(call_id)
        elif item_type == "function_call":
            if pending_outputs:
                flush_outputs()
            call_id = item.get("call_id") or item.get("id") or "function-call"
            arguments = item.get("arguments", {})
            if not isinstance(arguments, str):
                arguments = json.dumps(arguments, separators=(",", ":"))
            call = {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": item.get("name", "tool"),
                    "arguments": arguments,
                },
            }
            if pending_signatures:
                attach_signature(call, pending_signatures.pop(0))
            if extra := _thought_signature_extra(item):
                call["extra_content"] = extra
            pending_calls.append(call)
            call_order.append(call_id)
        elif item_type in {"function_call_output", "custom_tool_call_output"}:
            pending_outputs.append(item)
    flush_outputs()
    flush_calls()
    return messages


def _tools(body: dict[str, Any]) -> list[dict[str, Any]]:
    return _tool_registry(body)[0]


def _custom_tool_names(body: dict[str, Any]) -> set[str]:
    return _tool_registry(body)[1]


def responses_to_chat(body: dict[str, Any]) -> dict[str, Any]:
    """Translate the supported Responses request fields to Chat Completions."""
    payload: dict[str, Any] = {
        "model": body.get("model", "gemini-3.7-flash"),
        "messages": _messages(body),
        "stream": bool(body.get("stream")),
    }
    tools = _tools(body)
    if tools:
        payload["tools"] = tools
    for source, target in (
        ("temperature", "temperature"),
        ("top_p", "top_p"),
        ("stop", "stop"),
        ("max_output_tokens", "max_tokens"),
    ):
        if source in body:
            payload[target] = body[source]
    reasoning = body.get("reasoning")
    if isinstance(reasoning, dict) and isinstance(reasoning.get("effort"), str):
        payload["reasoning_effort"] = reasoning["effort"]
    if "tool_choice" in body:
        choice = body["tool_choice"]
        if isinstance(choice, dict) and choice.get("type") == "function":
            payload["tool_choice"] = {"function": {"name": choice.get("name", "")}}
        else:
            payload["tool_choice"] = choice
    if "parallel_tool_calls" in body:
        payload["parallel_tool_calls"] = body["parallel_tool_calls"]
    response_format = body.get("text", {}).get("format") if isinstance(body.get("text"), dict) else None
    if isinstance(response_format, dict):
        format_type = response_format.get("type")
        if format_type == "json_object":
            payload["response_format"] = {"type": "json_object"}
        elif format_type == "json_schema":
            schema = {
                "name": response_format.get("name", "response"),
                "schema": response_format.get("schema", {}),
            }
            if "strict" in response_format:
                schema["strict"] = response_format["strict"]
            payload["response_format"] = {"type": "json_schema", "json_schema": schema}
    return payload


def _chat_usage_to_response(usage: dict[str, Any]) -> dict[str, int]:
    return {
        "input_tokens": int(usage.get("prompt_tokens", 0) or 0),
        "output_tokens": int(usage.get("completion_tokens", 0) or 0),
        "total_tokens": int(usage.get("total_tokens", 0) or 0),
    }


def _chat_to_response(
    value: dict[str, Any],
    requested_model: str,
    custom_tool_names: set[str] | None = None,
) -> dict[str, Any]:
    custom_tool_names = custom_tool_names or set()
    choices = value.get("choices") or [{}]
    message = choices[0].get("message") or {}
    output: list[dict[str, Any]] = []
    text = message.get("content") or ""
    message_signatures = _thought_signatures(message)
    reasoning_text = message.get("reasoning_content") or ""
    if message_signatures:
        for signature in message_signatures:
            output.append(_reasoning_item(signature))
    elif reasoning_text:
        output.append(_reasoning_item("", str(reasoning_text)))
    if text:
        output.append({
            "id": "msg_" + uuid4().hex,
            "type": "message",
            "status": "completed",
            "role": "assistant",
            "content": [{"type": "output_text", "text": text, "annotations": []}],
        })
    for call in message.get("tool_calls", []) or []:
        function = call.get("function", {})
        name = function.get("name", "")
        call_id = call.get("id", "")
        signature = _thought_signature(call)
        if signature:
            output.append(_reasoning_item(signature))
        if name in custom_tool_names:
            item = {
                "id": call_id or "ctc_" + uuid4().hex,
                "type": "custom_tool_call",
                "status": "completed",
                "call_id": call_id,
                "name": name,
                "input": _custom_tool_input(function.get("arguments", "")),
            }
            if extra := _thought_signature_extra(call):
                item["extra_content"] = extra
            output.append(item)
            continue
        item = {
            "id": call_id or "fc_" + uuid4().hex,
            "type": "function_call",
            "status": "completed",
            "call_id": call_id,
            "name": name,
            "arguments": function.get("arguments", "{}"),
        }
        if extra := _thought_signature_extra(call):
            item["extra_content"] = extra
        output.append(item)

    response: dict[str, Any] = {
        "id": "resp_" + uuid4().hex,
        "object": "response",
        "created_at": int(time.time()),
        "status": "completed",
        "model": requested_model,
        "output": output,
        "output_text": text,
    }
    if isinstance(value.get("usage"), dict):
        response["usage"] = _chat_usage_to_response(value["usage"])
    return response


def _response_frame(event: str, value: dict[str, Any], sequence: int) -> bytes:
    payload = dict(value)
    payload.setdefault("type", event)
    payload["sequence_number"] = sequence
    return (
        f"event: {event}\n"
        f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
    ).encode("utf-8")


def _response_stream(
    chat_response: StreamingResponse,
    requested_model: str,
    custom_tool_names: set[str] | None = None,
) -> StreamingResponse:
    """Translate the shared Chat SSE stream into Responses SSE events."""
    custom_tool_names = custom_tool_names or set()

    async def generate():
        response_id = "resp_" + uuid4().hex
        response: dict[str, Any] = {
            "id": response_id,
            "object": "response",
            "created_at": int(time.time()),
            "status": "in_progress",
            "model": requested_model,
            "output": [],
        }
        sequence = 0
        text_item: dict[str, Any] | None = None
        text_parts: list[str] = []
        tool_states: dict[int, dict[str, Any]] = {}
        usage: dict[str, Any] | None = None
        stream_error: dict[str, Any] | None = None
        buffer = ""

        def frame(event: str, value: dict[str, Any]) -> bytes:
            nonlocal sequence
            sequence += 1
            return _response_frame(event, value, sequence)

        def output_index(item: dict[str, Any], outputs: list[dict[str, Any]] | None = None) -> int:
            source = response["output"] if outputs is None else outputs
            for index, candidate in enumerate(source):
                if candidate is item:
                    return index
            return -1

        def add_reasoning_carrier(signature: str) -> tuple[int, dict[str, Any]] | None:
            signature = signature.strip()
            if not signature:
                return None
            item = _reasoning_item(signature)
            index = len(response["output"])
            response["output"].append(item)
            return index, item

        def ensure_text_item():
            nonlocal text_item
            if text_item is not None:
                return
            text_item = {
                "id": "msg_" + uuid4().hex,
                "type": "message",
                "status": "in_progress",
                "role": "assistant",
                "content": [],
            }

        def ensure_tool(index: int, call: dict[str, Any]) -> dict[str, Any]:
            state = tool_states.get(index)
            function = call.get("function") or {}
            if state is None:
                call_id = call.get("id") or "fc_" + uuid4().hex
                name = function.get("name", "")
                custom = name in custom_tool_names
                item = {
                    "id": call_id,
                    "type": "custom_tool_call" if custom else "function_call",
                    "status": "in_progress",
                    "call_id": call_id,
                    "name": name,
                }
                item["input" if custom else "arguments"] = ""
                state = {
                    "item": item,
                    "arguments": "",
                    "name": name,
                    "custom": custom,
                }
                if extra := _thought_signature_extra(call):
                    item["extra_content"] = extra
                tool_states[index] = state
                response["output"].append(item)
            elif function.get("name") and not state["name"]:
                state["name"] = function["name"]
                state["item"]["name"] = function["name"]
                state["custom"] = function["name"] in custom_tool_names
            if extra := _thought_signature_extra(call):
                state["item"]["extra_content"] = extra
            return state

        async def consume(raw: bytes | str):
            nonlocal buffer, usage, stream_error
            buffer += raw.decode("utf-8") if isinstance(raw, bytes) else raw
            while "\n\n" in buffer:
                event, buffer = buffer.split("\n\n", 1)
                for line in event.splitlines():
                    if not line.startswith("data:"):
                        continue
                    value = line[5:].strip()
                    if not value or value == "[DONE]":
                        continue
                    try:
                        chunk = json.loads(value)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(chunk.get("error"), dict):
                        stream_error = chunk["error"]
                        continue
                    if isinstance(chunk.get("usage"), dict):
                        usage = _chat_usage_to_response(chunk["usage"])
                    choices = chunk.get("choices") or []
                    delta = choices[0].get("delta", {}) if choices else {}
                    for signature in _thought_signatures(delta):
                        carrier = add_reasoning_carrier(signature)
                        if carrier:
                            carrier_index, carrier_item = carrier
                            added_item = {**carrier_item, "status": "in_progress"}
                            yield frame(
                                "response.output_item.added",
                                {"output_index": carrier_index, "item": added_item},
                            )
                            yield frame(
                                "response.output_item.done",
                                {"output_index": carrier_index, "item": carrier_item},
                            )
                    text = delta.get("content") or ""
                    if text:
                        is_new_text = text_item is None
                        ensure_text_item()
                        if is_new_text:
                            text_output_index = len(response["output"])
                            response["output"].append(text_item)
                            yield frame(
                                "response.output_item.added",
                                {"output_index": text_output_index, "item": text_item},
                            )
                            yield frame(
                                "response.content_part.added",
                                {
                                    "item_id": text_item["id"],
                                    "output_index": text_output_index,
                                    "content_index": 0,
                                    "part": {"type": "output_text", "text": "", "annotations": []},
                                },
                            )
                        text_parts.append(str(text))
                        yield frame(
                            "response.output_text.delta",
                            {
                                "item_id": text_item["id"],
                                "output_index": output_index(text_item),
                                "content_index": 0,
                                "delta": str(text),
                            },
                        )
                    for call in delta.get("tool_calls", []) or []:
                        index = int(call.get("index", 0) or 0)
                        is_new_tool = index not in tool_states
                        if is_new_tool and (signature := _thought_signature(call)):
                            carrier = add_reasoning_carrier(signature)
                            if carrier:
                                carrier_index, carrier_item = carrier
                                added_item = {**carrier_item, "status": "in_progress"}
                                yield frame(
                                    "response.output_item.added",
                                    {"output_index": carrier_index, "item": added_item},
                                )
                                yield frame(
                                    "response.output_item.done",
                                    {"output_index": carrier_index, "item": carrier_item},
                                )
                        state = ensure_tool(index, call)
                        function = call.get("function") or {}
                        if is_new_tool:
                            yield frame(
                                "response.output_item.added",
                                {
                                    "output_index": output_index(state["item"]),
                                    "item": state["item"],
                                },
                            )
                        arguments = function.get("arguments") or ""
                        if arguments:
                            state["arguments"] += str(arguments)
                            if not state["custom"]:
                                call_output_index = output_index(state["item"])
                                yield frame(
                                    "response.function_call_arguments.delta",
                                    {
                                        "item_id": state["item"]["id"],
                                        "output_index": call_output_index,
                                        "delta": str(arguments),
                                    },
                                )

        try:
            yield frame("response.created", {"response": response})
            async for raw in chat_response.body_iterator:
                async for event in consume(raw):
                    yield event
            if buffer:
                async for event in consume("\n\n"):
                    yield event

            if stream_error:
                yield frame(
                    "error",
                    {
                        "message": stream_error.get("message", "Upstream stream failed"),
                        "error": stream_error,
                    },
                )
                return

            outputs: list[dict[str, Any]] = list(response["output"])
            if text_item is not None:
                text = "".join(text_parts)
                text_item["status"] = "completed"
                text_item["content"] = [{"type": "output_text", "text": text, "annotations": []}]
                text_output_index = output_index(text_item, outputs)
                if text_output_index < 0:
                    text_output_index = len(outputs)
                    outputs.append(text_item)
                yield frame(
                    "response.output_text.done",
                    {"item_id": text_item["id"], "output_index": text_output_index, "content_index": 0, "text": text},
                )
                yield frame(
                    "response.content_part.done",
                    {
                        "item_id": text_item["id"],
                        "output_index": text_output_index,
                        "content_index": 0,
                        "part": text_item["content"][0],
                    },
                )
                yield frame("response.output_item.done", {"output_index": text_output_index, "item": text_item})

            for index, state in sorted(tool_states.items()):
                item = state["item"]
                item["status"] = "completed"
                item["name"] = state["name"]
                call_output_index = output_index(item, outputs)
                if call_output_index < 0:
                    call_output_index = len(outputs)
                    outputs.append(item)
                if state["custom"]:
                    custom_input = _custom_tool_input(state["arguments"])
                    item["input"] = custom_input
                    yield frame(
                        "response.custom_tool_call_input.delta",
                        {"item_id": item["id"], "output_index": call_output_index, "delta": custom_input},
                    )
                else:
                    item["arguments"] = state["arguments"]
                if not state["custom"]:
                    yield frame(
                        "response.function_call_arguments.done",
                        {"item_id": item["id"], "output_index": call_output_index, "arguments": item["arguments"]},
                    )
                yield frame("response.output_item.done", {"output_index": call_output_index, "item": item})

            response["status"] = "completed"
            response["output"] = outputs
            response["output_text"] = "".join(text_parts)
            if usage is not None:
                response["usage"] = usage
            yield frame("response.completed", {"response": response})
        except Exception as exc:
            yield frame("error", {"message": f"Responses stream failed: {type(exc).__name__}: {exc}"})
        finally:
            close = getattr(chat_response.body_iterator, "aclose", None)
            if close:
                await close()

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/v1/responses")
async def responses(request: Request):
    body = await request.json()
    chat_body = responses_to_chat(body)
    custom_tool_names = _custom_tool_names(body)
    result = await _run_chat_completion(request, chat_body)
    if isinstance(result, StreamingResponse):
        return _response_stream(result, body.get("model", chat_body["model"]), custom_tool_names)
    if not isinstance(result, JSONResponse) or result.status_code != 200:
        return result
    value = json.loads(result.body)
    return JSONResponse(content=_chat_to_response(
        value,
        body.get("model", chat_body["model"]),
        custom_tool_names,
    ))
