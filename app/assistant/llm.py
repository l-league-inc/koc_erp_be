import json
from typing import Any

from django.conf import settings
from ninja.errors import HttpError


def _client():
    if not settings.OPENAI_API_KEY:
        raise HttpError(503, "언어 모델 키가 없습니다.")
    from openai import OpenAI

    return OpenAI(api_key=settings.OPENAI_API_KEY)


def _to_openai_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for message in messages:
        role = message["role"]
        if role == "assistant" and message.get("tool_calls"):
            payload.append(
                {
                    "role": "assistant",
                    "content": message.get("content") or "",
                    "tool_calls": [
                        {
                            "id": call["id"],
                            "type": "function",
                            "function": {
                                "name": call["name"],
                                "arguments": json.dumps(call["arguments"], ensure_ascii=False),
                            },
                        }
                        for call in message["tool_calls"]
                    ],
                }
            )
            continue
        if role == "tool":
            payload.append(
                {
                    "role": "tool",
                    "tool_call_id": message["tool_call_id"],
                    "content": message["content"],
                }
            )
            continue
        payload.append({"role": role, "content": message.get("content") or ""})
    return payload


def complete(messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        response = _client().chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=_to_openai_messages(messages),
            tools=tools,
        )
    except HttpError:
        raise
    except Exception:
        raise HttpError(502, "언어 모델 호출에 실패했습니다.") from None
    message = response.choices[0].message
    tool_calls = []
    for call in message.tool_calls or []:
        raw = call.function.arguments or "{}"
        try:
            arguments = json.loads(raw)
        except json.JSONDecodeError:
            arguments = {"_raw": raw}
        if not isinstance(arguments, dict):
            arguments = {"_raw": raw}
        tool_calls.append(
            {"id": call.id, "name": call.function.name, "arguments": arguments}
        )
    return {"content": message.content or "", "tool_calls": tool_calls}


def complete_json(messages: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        response = _client().chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=_to_openai_messages(messages),
            response_format={"type": "json_object"},
        )
        parsed = json.loads(response.choices[0].message.content or "{}")
    except HttpError:
        raise
    except Exception:
        raise HttpError(502, "언어 모델 호출에 실패했습니다.") from None
    if not isinstance(parsed, dict):
        raise HttpError(502, "언어 모델 응답을 해석하지 못했습니다.")
    return parsed
