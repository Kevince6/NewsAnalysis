"""读取302的SSE响应；逐行留存，重建自然回答及平台来源元数据。"""

from contextlib import nullcontext
import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request

import search_302 as api


def merge_list(existing, incoming):
    if not isinstance(incoming, list) or not incoming:
        return existing
    if incoming[:len(existing)] == existing:
        return incoming
    if existing[:len(incoming)] == incoming:
        return existing
    return existing + incoming


def merge_event(result, event):
    for name in ("id", "model", "created", "system_fingerprint", "service_tier"):
        if event.get(name) is not None:
            result[name] = event[name]
    if event.get("usage"):
        result["usage"] = event["usage"]
    if event.get("citations"):
        result["citations"] = merge_list(result.get("citations", []), event["citations"])
    for choice in event.get("choices") or []:
        if choice.get("index", 0) != 0:
            continue
        target = result["choices"][0]
        delta = choice.get("delta") or choice.get("message") or {}
        message = target["message"]
        for name in ("content", "reasoning_content", "refusal"):
            if isinstance(delta.get(name), str):
                message[name] = (message.get(name) or "") + delta[name]
        if delta.get("annotations"):
            message["annotations"] = merge_list(message.get("annotations", []), delta["annotations"])
        if choice.get("finish_reason") is not None:
            target["finish_reason"] = choice["finish_reason"]


def request_stream(base_url, path, key, timeout, payload, stream_path=None):
    request = Request(
        base_url.rstrip("/") + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )
    result = {"object": "chat.completion", "choices": [{
        "index": 0, "message": {"role": "assistant", "content": ""}, "finish_reason": None,
    }]}
    request_id = None
    chunks = []
    seen_done = False
    started = time.monotonic()
    output = stream_path.open("x", encoding="utf-8") if stream_path else nullcontext(None)
    try:
        with output as transcript:
            with api.build_opener(api.NoRedirect()).open(request, timeout=timeout) as response:
                request_id = response.headers.get("request-id") or response.headers.get("x-request-id")
                content_type = response.headers.get("Content-Type", "")
                if "application/json" in content_type and "event-stream" not in content_type:
                    body = response.read()
                    if transcript:
                        transcript.write(api.redact(body.decode("utf-8", errors="replace"), key))
                    decoded = api.decode_body(body)
                    if not isinstance(decoded, dict) or decoded.get("error"):
                        raise api.APIError("流式请求返回错误JSON", response=decoded, request_id=request_id)
                    return decoded, request_id
                data_lines = []
                def consume(lines):
                    nonlocal seen_done, result
                    text = "\n".join(lines)
                    if text.strip() == "[DONE]":
                        seen_done = True
                        return
                    if not text.strip():
                        return
                    event = json.loads(text)
                    if event.get("error"):
                        raise api.APIError("流式接口返回error字段", response=event, request_id=request_id)
                    if not stream_path:
                        chunks.append(event)
                    merge_event(result, event)
                for raw in response:
                    line = raw.decode("utf-8-sig", errors="replace")
                    if transcript:
                        transcript.write(api.redact(line, key))
                        transcript.flush()
                    if time.monotonic() - started > timeout:
                        raise TimeoutError("流式响应超过本次请求的总时间限制")
                    stripped = line.rstrip("\r\n")
                    if not stripped:
                        if data_lines:
                            consume(data_lines)
                            data_lines = []
                            if seen_done:
                                break
                    elif stripped.startswith("data:"):
                        data_lines.append(stripped[5:].lstrip())
                if data_lines:
                    consume(data_lines)
    except HTTPError as error:
        raise api.APIError(
            f"HTTP {error.code}", status=error.code, response=api.decode_body(error.read()),
            request_id=error.headers.get("request-id") or error.headers.get("x-request-id"),
        ) from None
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        raise api.APIError("流式连接中断：" + str(error), response=result, request_id=request_id) from None
    if not seen_done and not result["choices"][0]["finish_reason"]:
        raise api.APIError("流式响应缺少完成标记，已保留收到的内容。", response=result, request_id=request_id)
    result["_transport"] = "sse"
    if not stream_path:
        result["_stream_events"] = chunks
    return result, request_id
