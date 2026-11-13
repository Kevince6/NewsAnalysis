"""302.AI 三模型新闻搜索；Python 3.10+，仅使用标准库。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from uuid import uuid4
from credentials_302 import load_api_key


HERE = Path(__file__).resolve().parent
ALIASES = ("doubao", "deepseek", "qwen")
ENGINES = ("search1api", "tavily", "exa", "bochaai", "metaso")
BEIJING = timezone(timedelta(hours=8), name="Asia/Shanghai")


def now_beijing():
    return datetime.now(BEIJING)


def resolve_query_date(value):
    if value == "run_date":
        return now_beijing().date().isoformat()
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("query_date须为run_date或YYYY-MM-DD格式的日期。")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise ValueError("query_date不是有效日期。") from None


class NoRedirect(HTTPRedirectHandler):
    # 不将携带密钥的请求自动转发到其他地址。
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class APIError(Exception):
    def __init__(self, message, *, status=None, response=None, request_id=None):
        super().__init__(message)
        self.status = status
        self.response = response
        self.request_id = request_id


def redact(value, key):
    """平台错误消息可能回显密钥，写文件及显示错误前统一处理。"""
    if isinstance(value, str):
        return value.replace(key, "[REDACTED]") if key else value
    if isinstance(value, list):
        return [redact(item, key) for item in value]
    if isinstance(value, dict):
        return {redact(name, key): redact(item, key) for name, item in value.items()}
    return value


def save_json(path, value, key=""):
    # x 模式拒绝覆盖；每次运行也使用新的目录。
    with path.open("x", encoding="utf-8") as handle:
        json.dump(redact(value, key), handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def decode_body(body):
    text = body.decode("utf-8-sig", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def api_request(base_url, path, key, timeout, payload=None):
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        base_url.rstrip("/") + path,
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="GET" if payload is None else "POST",
    )
    try:
        with build_opener(NoRedirect()).open(request, timeout=timeout) as response:
            result = decode_body(response.read())
            request_id = response.headers.get("request-id") or response.headers.get("x-request-id")
    except HTTPError as error:
        result = decode_body(error.read())
        raise APIError(
            f"HTTP {error.code}", status=error.code, response=result,
            request_id=error.headers.get("request-id") or error.headers.get("x-request-id"),
        ) from None
    except (URLError, TimeoutError, OSError) as error:
        raise APIError(f"网络请求失败：{error}。未自动重试，请先检查平台调用日志。") from None
    if not isinstance(result, dict):
        raise APIError("接口未返回JSON对象", response=result, request_id=request_id)
    if result.get("error"):
        raise APIError("接口返回error字段", response=result, request_id=request_id)
    return result, request_id


def load_config(path):
    config = json.loads(path.read_text(encoding="utf-8-sig"))
    if "system_prompt_file" in config:
        if "system_prompt" in config:
            raise ValueError("system_prompt_file与system_prompt请只配置一项。")
        prompt_path = path.parent / config["system_prompt_file"]
        config["system_prompt"] = prompt_path.read_text(encoding="utf-8-sig").strip()
    if not isinstance(config.get("system_prompt"), str) or not config["system_prompt"].strip():
        raise ValueError("公共提示词不能为空。")
    config["prompt_version"] = config.get("prompt_version", "unversioned")
    config["query_date"] = resolve_query_date(config.get("query_date", "run_date"))
    address = urlsplit(config["base_url"])
    if address.scheme != "https" or not address.netloc or address.query or address.fragment:
        raise ValueError("base_url必须是HTTPS接口地址，且不包含查询参数。")
    if config["search_service"] not in ENGINES:
        raise ValueError("search_service不在302文档支持的搜索服务列表中。")
    if not 1 <= int(config["search_results"]) <= 20:
        raise ValueError("search_results必须在1至20之间。")
    if not 0 < float(config["timeout_seconds"]) <= 3600:
        raise ValueError("timeout_seconds必须大于0且不超过3600。")
    for alias in ALIASES:
        model = config["models"][alias]
        if not isinstance(model, str) or not model.strip():
            raise ValueError(f"{alias}的模型ID为空。")
    return config


def load_questions(cards_path, limit, news_ids=None):
    cards = json.loads(cards_path.read_text(encoding="utf-8-sig"))
    if not isinstance(cards, list):
        raise ValueError("新闻卡文件顶层应为数组。")
    wanted = set(news_ids or [])
    if wanted:
        missing = wanted - {str(card["id"]) for card in cards}
        if missing:
            raise ValueError("未找到新闻ID：" + ", ".join(sorted(missing)))
    questions = []
    for card in cards:
        if wanted and str(card["id"]) not in wanted:
            continue
        for index, original in enumerate(card.get("questions", []), 1):
            if not isinstance(original, str):
                raise ValueError("questions中的每个问题都必须是字符串。")
            question = re.sub(r"^【(?:开放|事实)】\s*", "", original).strip()
            if not question:
                raise ValueError(f"新闻{card['id']}的第{index}个问题为空。")
            # facts、summary、sources等核查材料不进入请求。
            questions.append({
                "news_id": card["id"], "question_index": index,
                "question_original": original, "question": question,
            })
    if not questions:
        raise ValueError("未找到可运行的问题。")
    return questions[:limit]


def compose_system_prompt(config):
    return (
        config["system_prompt"].strip()
        + "\n\n查询日期：" + config["query_date"]
        + "（北京时间，UTC+8）。问题中的“现在”“近期”“最新”以此日期为参照；"
        + "问题明确指定时间范围时，以问题为准。"
    )


def build_payload(config, alias, question):
    return {
        "model": config["models"][alias],
        "messages": [
            {"role": "system", "content": compose_system_prompt(config)},
            {"role": "user", "content": question},
        ],
        "web-search": True,
        "search-service": config["search_service"],
        "search-results": int(config["search_results"]),
        "stream": False,
    }


def is_http_url(value):
    if not isinstance(value, str):
        return False
    try:
        address = urlsplit(value)
        return address.scheme in ("https", "http") and bool(address.netloc)
    except ValueError:
        return False


def extract_sources(response, message):
    """仅提取接口元数据中的来源；不从模型正文猜测或补造链接。"""
    sources = []
    citations = response.get("citations") or []
    if isinstance(citations, list):
        for index, item in enumerate(citations, 1):
            url = item if isinstance(item, str) else (
                item.get("url") or item.get("link") if isinstance(item, dict) else None
            )
            if is_http_url(url):
                sources.append({
                    "index": index, "url": url,
                    "title": item.get("title") if isinstance(item, dict) else None,
                    "origin": "citations",
                })
    annotations = message.get("annotations") or []
    if isinstance(annotations, list):
        for index, item in enumerate(annotations):
            if not isinstance(item, dict) or item.get("type") != "url_citation":
                continue
            citation = item.get("url_citation") or item
            if not isinstance(citation, dict):
                continue
            url = citation.get("url")
            if is_http_url(url):
                sources.append({
                    "index": None, "url": url, "title": citation.get("title"),
                    "origin": f"choices[0].message.annotations[{index}]",
                    "start_index": citation.get("start_index"),
                    "end_index": citation.get("end_index"),
                })
    # 保留顺序与重复项，避免改变正文[1]等编号所对应的原始来源。
    return sources


def normalize(response):
    choices = response.get("choices") or []
    choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
    message = choice.get("message") or {}
    message = message if isinstance(message, dict) else {}
    answer = message.get("content")
    if isinstance(answer, list):
        answer = "\n".join(
            item["text"] for item in answer
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        )
    answer = answer if isinstance(answer, str) else ""
    sources = extract_sources(response, message)
    notes = []
    if not answer.strip():
        notes.append("回答正文为空。")
    if not sources:
        notes.append("未返回平台来源链接；仅凭正文中的链接不能确认搜索是否成功。")
    if choice.get("finish_reason") == "length":
        notes.append("输出达到长度限制，回答可能被截断。")
    if message.get("refusal") or choice.get("finish_reason") == "content_filter":
        notes.append("接口报告拒绝回答或内容过滤。")
    if message.get("tool_calls"):
        notes.append("响应中仍有待执行的工具调用，回答可能未完成。")
    return {
        "status": "needs_review" if notes else "ok",
        "model_returned": response.get("model"),
        "answer": answer,
        "sources": sources,
        "usage": response.get("usage"),
        "finish_reason": choice.get("finish_reason"),
        "note": notes,
    }


def new_run(root):
    directory = root / (now_beijing().strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:8])
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "raw").mkdir()
    return directory


def available_models(response):
    entries = response.get("data")
    if not isinstance(entries, list):
        raise ValueError("模型列表缺少data数组，请检查本次保存的models.json。")
    return {item["id"] for item in entries if isinstance(item, dict) and isinstance(item.get("id"), str)}


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--prompt", help="让所选模型回答同一个问题")
    modes.add_argument("--cards", type=Path, help="读取已有新闻卡中的questions；不会上传核查材料")
    modes.add_argument("--list-models", action="store_true", help="查询账号可用模型，不调用问答")
    parser.add_argument("--config", type=Path, default=HERE / "config.json")
    parser.add_argument("--models", nargs="+", choices=ALIASES, default=list(ALIASES))
    parser.add_argument("--search-service", choices=ENGINES)
    parser.add_argument("--query-date", help="相对时间的基准：YYYY-MM-DD或run_date")
    parser.add_argument("--limit", type=int, default=1, help="新闻卡模式最多取几个问题，默认1")
    parser.add_argument("--news-ids", nargs="+", help="新闻卡模式仅选取这些新闻ID")
    parser.add_argument("--output", type=Path, default=HERE / "outputs")
    parser.add_argument("--dry-run", action="store_true", help="只预览请求，不联网、不需要密钥")
    args = parser.parse_args(argv)
    if args.limit < 1:
        parser.error("--limit必须大于0")
    if args.prompt is not None and not args.prompt.strip():
        parser.error("--prompt不能为空")
    if args.news_ids and not args.cards:
        parser.error("--news-ids仅用于--cards模式")
    if args.dry_run and args.list_models:
        parser.error("--list-models需要实际查询；--dry-run用于预览问题请求")
    args.models = list(dict.fromkeys(args.models))
    return args


def main(argv=None):
    args = parse_args(argv)
    config = load_config(args.config)
    if args.query_date:
        config["query_date"] = resolve_query_date(args.query_date)
    if args.search_service:
        config["search_service"] = args.search_service
    prompt_sha256 = hashlib.sha256(compose_system_prompt(config).encode("utf-8")).hexdigest()
    questions = [] if args.list_models else (
        load_questions(args.cards, args.limit, args.news_ids) if args.cards
        else [{"question": args.prompt}]
    )
    if args.dry_run:
        print(json.dumps({
            "endpoint": config["base_url"].rstrip("/") + "/chat/completions",
            "planned_calls": len(questions) * len(args.models),
            "query_date": config["query_date"],
            "prompt_version": config["prompt_version"],
            "prompt_sha256": prompt_sha256,
            "requests": [
                {"context": item, "body": build_payload(config, alias, item["question"])}
                for item in questions for alias in args.models
            ],
        }, ensure_ascii=False, indent=2))
        return 0

    key = load_api_key()
    if not key:
        raise ValueError("未设置AI302_API_KEY环境变量。可先加--dry-run离线预览。")
    if "\n" in key or "\r" in key:
        raise ValueError("API Key不能包含换行符。")
    directory = new_run(args.output)
    print(f"本次结果目录：{directory}")
    try:
        listing, _ = api_request(
            config["base_url"], "/models?llm=1", key, config["timeout_seconds"]
        )
    except APIError as error:
        save_json(directory / "preflight_error.json", {
            "error": str(error), "http_status": error.status, "response": error.response,
        }, key)
        print(f"模型列表查询失败：{redact(str(error), key)}；详情已保存。")
        return 1
    save_json(directory / "models.json", listing, key)
    ids = available_models(listing)
    missing = []
    for alias in args.models:
        model_id = config["models"][alias]
        found = model_id in ids
        print(f"{alias}: {model_id}  {'可用' if found else '列表中未找到'}")
        if not found:
            missing.append(model_id)
    if args.list_models:
        print("三家相关模型：")
        for model_id in sorted(ids):
            if any(word in model_id.lower() for word in ("doubao", "deepseek", "qwen")):
                print("  " + model_id)
        return 1 if missing else 0
    if missing:
        print("请按models.json中的实际ID修改配置后重跑；本次未调用问答，也未自动替换模型。")
        return 1

    save_json(directory / "run.json", {
        "started_at": now_beijing().isoformat(),
        "config": config,
        "system_message": compose_system_prompt(config),
        "prompt_sha256": prompt_sha256,
        "models": args.models,
        "question_count": len(questions),
        "planned_calls": len(questions) * len(args.models),
        "source_files": {"cards": str(args.cards) if args.cards else None},
    }, key)
    print(f"计划调用：{len(questions)}个问题 × {len(args.models)}个模型。")
    failures = 0
    sequence = 0
    for item in questions:
        for alias in args.models:
            sequence += 1
            filename = f"{sequence:04d}_{alias}.json"
            payload = build_payload(config, alias, item["question"])
            record = {
                **item,
                "provider": "302.ai",
                "model": alias,
                "model_requested": config["models"][alias],
                "search_service": config["search_service"],
                "query_date": config["query_date"],
                "prompt_version": config["prompt_version"],
                "prompt_sha256": prompt_sha256,
                "requested_at": now_beijing().isoformat(),
                "raw_file": "raw/" + filename,
            }
            start = time.monotonic()
            error_status = None
            try:
                response, request_id = api_request(
                    config["base_url"], "/chat/completions", key,
                    config["timeout_seconds"], payload,
                )
                record.update(normalize(response))
                record["request_id"] = request_id or response.get("id")
                raw = {"request": payload, "response": response}
            except APIError as error:
                error_status = error.status
                record.update({
                    "status": "error", "answer": None, "sources": [],
                    "request_id": error.request_id,
                    "note": [str(error)], "http_status": error.status,
                })
                raw = {"request": payload, "error": str(error), "response": error.response}
            record["duration_seconds"] = round(time.monotonic() - start, 3)
            save_json(directory / "raw" / filename, raw, key)
            save_json(directory / filename, record, key)
            if record["status"] != "ok":
                failures += 1
            print(f"[{sequence}] {alias}: {record['status']}，来源条目{len(record['sources'])}，{filename}")
            if error_status in (401, 402, 403):
                print("鉴权、额度或权限异常，停止后续请求。详情见本次raw目录。")
                return 1
    print(f"已完成。需检查或失败的回答：{failures}。")
    return 1 if failures else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, KeyError, TypeError, OSError) as error:
        secret = os.environ.get("AI302_API_KEY", "").strip()
        print(f"错误：{redact(str(error), secret)}", file=sys.stderr)
        sys.exit(2)
