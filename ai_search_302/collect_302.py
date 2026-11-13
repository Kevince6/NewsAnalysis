"""三模型批量采集：先试跑、并发、追加日志、保留原始响应和断点续跑。"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

import search_302 as api
from credentials_302 import load_api_key


def append_json(path, data, key=""):
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(api.redact(data, key), ensure_ascii=False) + "\n")
        handle.flush()


def read_events(path):
    if not path.is_file():
        return []
    events = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def emit(directory, event, key="", **fields):
    append_json(directory / "events.jsonl", {
        "time": api.now_beijing().isoformat(), "event": event, "pid": os.getpid(), **fields,
    }, key)


@contextmanager
def run_lock(path):
    """锁由操作系统随进程释放；保留锁文件，不通过删除文件解锁。"""
    handle = path.open("a+b")
    try:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise ValueError("同一采集目录已有进程运行，不能重复启动。") from None
    try:
        yield
    finally:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def prepare(cards, config_path, output, workers=3, limit=100000):
    config = api.load_config(config_path)
    questions = api.load_questions(cards, limit)
    directory = api.new_run(output)
    (directory / "answers").mkdir()
    tasks = []
    for question in questions:
        for alias in api.ALIASES:
            tasks.append({"task_id": f"T{len(tasks) + 1:04d}", "model": alias, **question})
    # 先用旅行证件题测试通路；这三个回答纳入正式结果，不重复计费。
    pilot = [task["task_id"] for task in tasks if task.get("news_id") == "E022" and task["question_index"] == 1]
    if not pilot:
        pilot = [task["task_id"] for task in tasks[:3]]
    system = api.compose_system_prompt(config)
    api.save_json(directory / "collection.json", {
        "created_at": api.now_beijing().isoformat(),
        "config": config, "system_message": system,
        "prompt_sha256": hashlib.sha256(system.encode("utf-8")).hexdigest(),
        "cards_path": str(cards.resolve()),
        "cards_sha256": hashlib.sha256(cards.read_bytes()).hexdigest(),
        "question_count": len(questions), "planned_calls": len(tasks),
        "workers": workers, "pilot_task_ids": pilot,
    })
    api.save_json(directory / "tasks.json", tasks)
    emit(directory, "prepared", state="prepared", total=len(tasks))
    return directory


def records(directory):
    latest = {}
    attempts = {}
    for path in sorted((directory / "answers").glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        task_id = record.get("task_id")
        attempt = record.get("attempt", 1)
        attempts[task_id] = max(attempts.get(task_id, 0), attempt)
        if task_id not in latest or attempt > latest[task_id].get("attempt", 1):
            latest[task_id] = record
    return latest, attempts


def collect_one(directory, manifest, task, attempt, key):
    config = manifest["config"]
    alias = task["model"]
    filename = f"{task['task_id']}_{alias}_a{attempt:03d}_{uuid4().hex[:6]}.json"
    payload = api.build_payload(config, alias, task["question"])
    record = {
        **task, "attempt": attempt, "provider": "302.ai",
        "model_requested": config["models"][alias],
        "query_date": config["query_date"], "search_service": config["search_service"],
        "prompt_version": config["prompt_version"], "prompt_sha256": manifest["prompt_sha256"],
        "requested_at": api.now_beijing().isoformat(),
        "raw_file": "raw/" + filename,
    }
    start = time.monotonic()
    try:
        response, request_id = api.api_request(
            config["base_url"], "/chat/completions", key, config["timeout_seconds"], payload,
        )
        record.update(api.normalize(response))
        record["request_id"] = request_id or response.get("id")
        raw = {"request": payload, "response": response}
    except api.APIError as error:
        record.update({
            "status": "error", "answer": None, "sources": [], "note": [str(error)],
            "http_status": error.status, "request_id": error.request_id,
        })
        raw = {"request": payload, "error": str(error), "response": error.response}
    except Exception as error:
        record.update({
            "status": "error", "answer": None, "sources": [],
            "note": ["客户端异常：" + str(error)],
        })
        raw = {"request": payload, "error": str(error)}
    record["duration_seconds"] = round(time.monotonic() - start, 3)
    api.save_json(directory / "raw" / filename, raw, key)
    api.save_json(directory / "answers" / filename, record, key)
    return record, filename


def stop_requested(directory):
    commands = read_events(directory / "control.jsonl")
    return bool(commands and commands[-1].get("action") == "stop")


def execute_phase(directory, manifest, tasks, attempts, key, stage):
    workers = manifest["workers"]
    iterator = iter(tasks)
    active = {}
    stopped = None
    errors = 0
    heartbeat = 0.0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        exhausted = False
        while active or not exhausted:
            if stop_requested(directory):
                stopped = stopped or "stopped"
            while not stopped and not exhausted and len(active) < workers:
                try:
                    task = next(iterator)
                except StopIteration:
                    exhausted = True
                    break
                attempt = attempts.get(task["task_id"], 0) + 1
                emit(directory, "task_started", key, task_id=task["task_id"], model=task["model"], attempt=attempt)
                future = pool.submit(collect_one, directory, manifest, task, attempt, key)
                active[future] = task
            if time.monotonic() - heartbeat >= 10:
                emit(directory, "heartbeat", key, state="stopping" if stopped else stage,
                     active=[{"task_id": item["task_id"], "model": item["model"],
                              "news_id": item.get("news_id")} for item in active.values()])
                heartbeat = time.monotonic()
            if not active:
                break
            finished, _ = wait(active, timeout=1, return_when=FIRST_COMPLETED)
            for future in finished:
                task = active.pop(future)
                record, filename = future.result()
                emit(directory, "task_finished", key, task_id=task["task_id"], model=task["model"],
                     status=record["status"], file="answers/" + filename, attempt=record["attempt"],
                     duration_seconds=record["duration_seconds"], sources=len(record["sources"]))
                print(f"{task['task_id']} {task['model']}: {record['status']}，来源{len(record['sources'])}", flush=True)
                errors = errors + 1 if record["status"] == "error" else 0
                if record.get("http_status") in (401, 402, 403, 429):
                    stopped = "blocked"
                if errors >= 5:
                    stopped = "blocked"
    return stopped


def run(directory, env_file=None, retry_failed=False):
    manifest = json.loads((directory / "collection.json").read_text(encoding="utf-8"))
    tasks = json.loads((directory / "tasks.json").read_text(encoding="utf-8"))
    with run_lock(directory / ".collector.lock"):
        key = load_api_key(env_file)
        if not key:
            emit(directory, "state", state="waiting_for_key")
            print("未找到密钥，请配置.env后使用相同目录续跑。", flush=True)
            return 2
        append_json(directory / "control.jsonl", {"action": "run", "time": api.now_beijing().isoformat()})
        emit(directory, "state", key, state="preflight")
        config = manifest["config"]
        try:
            listing, _ = api.api_request(config["base_url"], "/models?llm=1", key, config["timeout_seconds"])
            api.save_json(directory / ("models_" + uuid4().hex[:8] + ".json"), listing, key)
            ids = api.available_models(listing)
            missing = [value for value in config["models"].values() if value not in ids]
            if missing:
                emit(directory, "state", key, state="blocked", reason="模型列表中未找到：" + ", ".join(missing))
                return 1
        except api.APIError as error:
            api.save_json(directory / ("preflight_error_" + uuid4().hex[:8] + ".json"), {
                "error": str(error), "http_status": error.status, "response": error.response,
            }, key)
            emit(directory, "state", key, state="blocked", reason=str(error))
            return 1

        latest, attempts = records(directory)
        previous = read_events(directory / "events.jsonl")
        started = {event["task_id"] for event in previous if event.get("event") == "task_started"}
        uncertain = started - set(latest)
        if uncertain and not retry_failed:
            emit(directory, "state", key, state="blocked",
                 reason="发现已发出但未落盘的请求，请检查平台日志后用--retry-failed续跑。",
                 uncertain=sorted(uncertain))
            return 1
        pending = [
            task for task in tasks
            if task["task_id"] not in latest
            or (retry_failed and latest[task["task_id"]]["status"] == "error")
        ]
        pilot_ids = set(manifest["pilot_task_ids"])
        pilot = [task for task in pending if task["task_id"] in pilot_ids]
        emit(directory, "state", key, state="pilot")
        halted = execute_phase(directory, manifest, pilot, attempts, key, "pilot")
        latest, attempts = records(directory)
        if halted:
            emit(directory, "state", key, state=halted)
            return 1
        if any(task_id not in latest or latest[task_id]["status"] != "ok" for task_id in pilot_ids):
            emit(directory, "state", key, state="pilot_failed",
                 reason="试采集未全部取得完整回答及平台来源，请先检查试跑结果。")
            return 1
        emit(directory, "state", key, state="collecting")
        remaining = [task for task in pending if task["task_id"] not in pilot_ids]
        halted = execute_phase(directory, manifest, remaining, attempts, key, "collecting")
        latest, _ = records(directory)
        final = halted or ("completed_with_errors" if any(r["status"] == "error" for r in latest.values()) else "completed")
        emit(directory, "state", key, state=final, completed=len(latest), total=len(tasks))
        return 1 if halted or any(r["status"] == "error" for r in latest.values()) else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    create = subs.add_parser("prepare", help="只生成任务，不调用API")
    create.add_argument("--cards", type=Path, required=True)
    create.add_argument("--config", type=Path, default=api.HERE / "config.json")
    create.add_argument("--output", type=Path, default=api.HERE / "outputs")
    create.add_argument("--workers", type=int, choices=(1, 2, 3), default=3)
    create.add_argument("--limit", type=int, default=100000)
    execute = subs.add_parser("run", help="运行或续跑现有任务目录")
    execute.add_argument("directory", type=Path)
    execute.add_argument("--env-file", type=Path)
    execute.add_argument("--retry-failed", action="store_true", help="额外重试接口失败及中断未落盘的请求")
    args = parser.parse_args(argv)
    if args.command == "prepare":
        if args.limit < 1:
            parser.error("--limit必须大于0")
        print(prepare(args.cards, args.config, args.output, args.workers, args.limit))
        return 0
    return run(args.directory.resolve(), args.env_file, args.retry_failed)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    try:
        sys.exit(main())
    except Exception as error:
        try:
            secret = load_api_key()
        except Exception:
            secret = ""
        print(api.redact("采集异常：" + str(error), secret), file=sys.stderr)
        sys.exit(2)
