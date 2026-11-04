import json
from typing import Any

import requests
from django.conf import settings
from ninja.errors import HttpError

from assistant.models import ModelPreference

DEFAULT_MODEL = "gpt-6-luna"
_TIMEOUT = 120
MODELS: tuple[dict[str, str], ...] = (
    {
        "id": "gpt-6-luna",
        "provider": "openai",
        "name": "GPT-6 Luna",
        "description": "빠르고 가벼운 기본 모델",
    },
    {
        "id": "gpt-6.1-terra",
        "provider": "openai",
        "name": "GPT-6.1 Terra",
        "description": "일상 업무에 맞춘 균형 모델",
    },
    {
        "id": "gpt-6.1-sol",
        "provider": "openai",
        "name": "GPT-6.1 Sol",
        "description": "복잡한 지시와 여러 단계 작업에 강한 모델",
    },
    {
        "id": "claude-haiku-5-5",
        "provider": "anthropic",
        "name": "Claude Haiku 5.5",
        "description": "빠르고 가벼운 Claude",
    },
    {
        "id": "claude-sonnet-5-5",
        "provider": "anthropic",
        "name": "Claude Sonnet 5.5",
        "description": "일상 업무에 맞춘 Claude",
    },
    {
        "id": "claude-opus-5-5",
        "provider": "anthropic",
        "name": "Claude Opus 5.5",
        "description": "복잡한 지시와 여러 단계 작업에 강한 Claude",
    },
)
_BY_ID = {item["id"]: item for item in MODELS}
_OPENAI_EFFORT = {
    "gpt-6-luna": "none",
    "gpt-6.1-terra": "low",
    "gpt-6.1-sol": "low",
}


def list_models(user) -> dict[str, Any]:
    return {"selected": selected_model(user), "models": [dict(item) for item in MODELS]}


def selected_model(user) -> str:
    row = ModelPreference.objects.filter(user=user).first()
    if row is None or row.model not in _BY_ID:
        return DEFAULT_MODEL
    return row.model


def use_model(user, requested: str) -> str:
    cleaned = (requested or "").strip()
    if not cleaned:
        return selected_model(user)
    if cleaned not in _BY_ID:
        raise HttpError(400, "지원하지 않는 모델입니다.")
    ModelPreference.objects.update_or_create(user=user, defaults={"model": cleaned})
    return cleaned


def save_model(user, requested: str) -> dict[str, Any]:
    if not (requested or "").strip():
        raise HttpError(400, "모델이 필요합니다.")
    use_model(user, requested)
    return list_models(user)


def complete(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    model: str = "",
) -> dict[str, Any]:
    model_id = _require_model(model)
    try:
        if _BY_ID[model_id]["provider"] == "anthropic":
            return _anthropic_complete(model_id, messages, tools)
        return _openai_complete(model_id, messages, tools)
    except HttpError:
        raise
    except Exception:
        raise HttpError(502, "언어 모델 호출에 실패했습니다.") from None


def complete_json(messages: list[dict[str, Any]], model: str = "") -> dict[str, Any]:
    model_id = _require_model(model)
    try:
        if _BY_ID[model_id]["provider"] == "anthropic":
            text = _anthropic_text(model_id, messages)
        else:
            text = _openai_text(model_id, messages)
        parsed = _parse_json(text)
    except HttpError:
        raise
    except Exception:
        raise HttpError(502, "언어 모델 호출에 실패했습니다.") from None
    if not isinstance(parsed, dict):
        raise HttpError(502, "언어 모델 응답을 해석하지 못했습니다.")
    return parsed


def _require_model(model: str) -> str:
    model_id = (model or DEFAULT_MODEL).strip()
    if model_id not in _BY_ID:
        raise HttpError(400, "지원하지 않는 모델입니다.")
    return model_id


def _openai_key() -> str:
    key = getattr(settings, "OPENAI_API_KEY", "") or ""
    if not key:
        raise HttpError(503, "언어 모델 키가 없습니다.")
    return key


def _anthropic_key() -> str:
    key = getattr(settings, "ANTHROPIC_API_KEY", "") or ""
    if not key:
        raise HttpError(503, "언어 모델 키가 없습니다.")
    return key


def _post(url: str, headers: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
    try:
        response = requests.post(url, headers=headers, json=body, timeout=_TIMEOUT)
    except requests.RequestException:
        raise HttpError(502, "언어 모델 호출에 실패했습니다.") from None
    if response.status_code >= 400:
        raise HttpError(502, "언어 모델 호출에 실패했습니다.")
    try:
        data = response.json()
    except ValueError:
        raise HttpError(502, "언어 모델 호출에 실패했습니다.") from None
    if not isinstance(data, dict):
        raise HttpError(502, "언어 모델 응답을 해석하지 못했습니다.")
    return data


def _function_parameters(tool: dict[str, Any]) -> dict[str, Any]:
    function = tool.get("function") or tool
    parameters = function.get("parameters") or {"type": "object", "properties": {}}
    if not isinstance(parameters, dict):
        return {"type": "object", "properties": {}}
    return parameters


def _to_responses_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    converted = []
    for tool in tools:
        function = tool.get("function") or tool
        converted.append(
            {
                "type": "function",
                "name": function.get("name") or "",
                "description": function.get("description") or "",
                "parameters": _function_parameters(tool),
            }
        )
    return converted


def _to_responses_input(messages: list[dict[str, Any]]) -> tuple[str, list[Any]]:
    instructions: list[str] = []
    items: list[Any] = []
    for message in messages:
        role = message["role"]
        if role == "system":
            if message.get("content"):
                instructions.append(message["content"])
            continue
        if role == "assistant" and message.get("replay"):
            items.extend(message["replay"])
            continue
        if role == "assistant":
            if message.get("content"):
                items.append({"role": "assistant", "content": message["content"]})
            for call in message.get("tool_calls") or []:
                items.append(
                    {
                        "type": "function_call",
                        "call_id": call["id"],
                        "name": call["name"],
                        "arguments": json.dumps(call["arguments"], ensure_ascii=False),
                    }
                )
            continue
        if role == "tool":
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": message["tool_call_id"],
                    "output": message["content"],
                }
            )
            continue
        items.append({"role": role, "content": message.get("content") or ""})
    return "\n".join(instructions), items


def _openai_body(model_id: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
    instructions, items = _to_responses_input(messages)
    body: dict[str, Any] = {
        "model": model_id,
        "input": items,
        "reasoning": {"effort": _OPENAI_EFFORT[model_id]},
    }
    if instructions:
        body["instructions"] = instructions
    if tools:
        body["tools"] = _to_responses_tools(tools)
    else:
        body["text"] = {"format": {"type": "json_object"}}
    return body


def _openai_complete(model_id: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
    data = _post(
        "https://api.openai.com/v1/responses",
        {
            "Authorization": f"Bearer {_openai_key()}",
            "Content-Type": "application/json",
        },
        _openai_body(model_id, messages, tools),
    )
    content: list[str] = []
    tool_calls = []
    for item in data.get("output") or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "function_call":
            raw = item.get("arguments") or "{}"
            try:
                arguments = json.loads(raw) if isinstance(raw, str) else raw
            except json.JSONDecodeError:
                arguments = {"_raw": raw}
            if not isinstance(arguments, dict):
                arguments = {"_raw": raw}
            tool_calls.append(
                {
                    "id": item.get("call_id") or item.get("id") or "",
                    "name": item.get("name") or "",
                    "arguments": arguments,
                }
            )
            continue
        if item.get("type") == "message":
            for part in item.get("content") or []:
                if isinstance(part, dict) and part.get("text"):
                    content.append(str(part["text"]))
    text = "".join(content).strip() or str(data.get("output_text") or "")
    return {
        "content": text,
        "tool_calls": tool_calls,
        "replay": [item for item in data.get("output") or [] if isinstance(item, dict)],
    }


def _output_text(data: dict[str, Any]) -> str:
    text = str(data.get("output_text") or "").strip()
    if text:
        return text
    parts: list[str] = []
    for item in data.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            if isinstance(part, dict) and part.get("text"):
                parts.append(str(part["text"]))
    return "".join(parts).strip()


def _openai_text(model_id: str, messages: list[dict[str, Any]]) -> str:
    data = _post(
        "https://api.openai.com/v1/responses",
        {
            "Authorization": f"Bearer {_openai_key()}",
            "Content-Type": "application/json",
        },
        _openai_body(model_id, messages, []),
    )
    return _output_text(data)


def _to_anthropic_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    converted = []
    for tool in tools:
        function = tool.get("function") or tool
        converted.append(
            {
                "name": function.get("name") or "",
                "description": function.get("description") or "",
                "input_schema": _function_parameters(tool),
            }
        )
    return converted


def _to_anthropic_messages(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    system: list[str] = []
    converted: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []

    def flush() -> None:
        if pending:
            converted.append({"role": "user", "content": list(pending)})
            pending.clear()

    for message in messages:
        role = message["role"]
        if role == "system":
            if message.get("content"):
                system.append(message["content"])
            continue
        if role == "tool":
            pending.append(
                {
                    "type": "tool_result",
                    "tool_use_id": message["tool_call_id"],
                    "content": message["content"],
                }
            )
            continue
        flush()
        if role == "assistant" and message.get("replay"):
            converted.append({"role": "assistant", "content": message["replay"]})
            continue
        if role == "assistant" and message.get("tool_calls"):
            blocks: list[dict[str, Any]] = []
            if message.get("content"):
                blocks.append({"type": "text", "text": message["content"]})
            for call in message["tool_calls"]:
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": call["id"],
                        "name": call["name"],
                        "input": call["arguments"],
                    }
                )
            converted.append({"role": "assistant", "content": blocks})
            continue
        converted.append(
            {
                "role": "assistant" if role == "assistant" else "user",
                "content": message.get("content") or "",
            }
        )
    flush()
    return "\n".join(system), converted


def _anthropic_body(model_id: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
    system, payload = _to_anthropic_messages(messages)
    body: dict[str, Any] = {
        "model": model_id,
        "max_tokens": 16000,
        "messages": payload,
    }
    if system:
        body["system"] = system
    if tools:
        body["tools"] = _to_anthropic_tools(tools)
    if model_id in {"claude-haiku-5-5", "claude-sonnet-5-5"}:
        body["thinking"] = {"type": "between_tools"}
    return body


def _anthropic_post(body: dict[str, Any]) -> dict[str, Any]:
    return _post(
        "https://api.anthropic.com/v1/messages",
        {
            "x-api-key": _anthropic_key(),
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        body,
    )


def _anthropic_complete(
    model_id: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> dict[str, Any]:
    data = _anthropic_post(_anthropic_body(model_id, messages, tools))
    content: list[str] = []
    tool_calls = []
    replay = []
    for block in data.get("content") or []:
        if not isinstance(block, dict):
            continue
        replay.append(block)
        if block.get("type") == "text" and block.get("text"):
            content.append(str(block["text"]))
        elif block.get("type") == "tool_use":
            arguments = block.get("input") if isinstance(block.get("input"), dict) else {}
            tool_calls.append(
                {
                    "id": block.get("id") or "",
                    "name": block.get("name") or "",
                    "arguments": arguments,
                }
            )
    return {"content": "".join(content).strip(), "tool_calls": tool_calls, "replay": replay}


def _anthropic_text(model_id: str, messages: list[dict[str, Any]]) -> str:
    result = _anthropic_complete(model_id, messages, [])
    return result["content"]


def _parse_json(text: str) -> Any:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        cleaned = cleaned[start : end + 1]
    return json.loads(cleaned)
