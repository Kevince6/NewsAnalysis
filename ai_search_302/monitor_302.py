"""只读监控采集进度；--stop可请求采集器保存当前请求后停止。"""

import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys
import time
from datetime import datetime

sys.dont_write_bytecode = True
import collect_302 as batch
import search_302 as api


STATES = {
    "prepared": "任务已准备，尚未启动", "preflight": "检查账号及模型",
    "pilot": "三模型试采集中", "collecting": "正式采集中",
    "stopping": "正在保存当前请求并停止", "stopped": "已停止",
    "completed": "已完成", "completed_with_errors": "已完成，存在接口失败",
    "blocked": "已停止，需要处理接口问题", "pilot_failed": "试采集未通过，未继续批量请求",
    "waiting_for_key": "等待配置API Key", "interrupted": "进程已退出，可检查后续跑",
    "stalled": "心跳已过期，采集停滞",
}
TERMINAL = {"stopped", "completed", "completed_with_errors", "blocked", "pilot_failed", "waiting_for_key", "interrupted"}


def process_alive(pid):
    if not pid:
        return None
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return None
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, int(pid))
    if not handle:
        return None if ctypes.get_last_error() == 5 else False
    try:
        code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
            return None
        return code.value == 259
    finally:
        kernel.CloseHandle(handle)


def latest_run(root):
    candidates = list(root.glob("*/collection.json"))
    if not candidates:
        raise ValueError("未找到批量采集目录，请先prepare并启动采集器。")
    return max(candidates, key=lambda path: path.stat().st_mtime).parent


def snapshot(directory):
    manifest = json.loads((directory / "collection.json").read_text(encoding="utf-8"))
    latest, _ = batch.records(directory)
    try:
        events = batch.read_events(directory / "events.jsonl")
    except UnicodeError:
        events = []
    state, reason, pid, heartbeat = "prepared", None, None, None
    active = {}
    for event in events:
        if event.get("state"):
            state = event["state"]
            reason = event.get("reason")
        if event.get("pid"):
            pid = event["pid"]
        heartbeat = event.get("time")
        if event.get("event") == "task_started":
            active[event["task_id"]] = {"task_id": event["task_id"], "model": event["model"]}
        elif event.get("event") == "task_finished":
            active.pop(event["task_id"], None)
    alive = process_alive(pid)
    locked = batch.lock_held(directory / ".collector.lock")
    age = None
    if heartbeat:
        try:
            age = max(0, (api.now_beijing() - datetime.fromisoformat(heartbeat)).total_seconds())
        except ValueError:
            pass
    interrupted_tasks = []
    if state not in TERMINAL and state != "prepared":
        if locked is False or alive is False:
            state = "interrupted"
            reason = "采集进程未持有运行锁，旧日志不能视为正在运行。"
            interrupted_tasks = list(active.values())
            active = {}
        elif age is None or age > 60:
            state = "stalled"
            reason = "超过60秒没有新心跳；正在确认采集状态。"
    per_model = {
        alias: {"ok": 0, "needs_review": 0, "error": 0, "total": manifest["question_count"]}
        for alias in api.ALIASES
    }
    counts = {"ok": 0, "needs_review": 0, "error": 0}
    tokens = 0
    duration = 0.0
    for record in latest.values():
        status = record["status"]
        counts[status] = counts.get(status, 0) + 1
        per_model[record["model"]][status] += 1
        usage = record.get("usage") or {}
        if isinstance(usage.get("total_tokens"), (int, float)):
            tokens += usage["total_tokens"]
        duration += record.get("duration_seconds") or 0
    total = manifest["planned_calls"]
    eta = round(duration / len(latest) * max(0, total - len(latest)) / manifest["workers"]) if latest and state in ("pilot", "collecting") else None
    supervisor = batch.read_events(directory / "supervisor.jsonl")
    supervisor_event = supervisor[-1] if supervisor else {}
    supervisor_locked = batch.lock_held(directory / ".supervisor.lock")
    return {
        "directory": str(directory.resolve()), "state": state,
        "state_text": STATES.get(state, state), "reason": reason,
        "completed": len(latest), "total": total, **counts,
        "attempts": sum(event.get("event") == "task_started" for event in events),
        "historical_error_attempts": sum(event.get("event") == "task_finished" and event.get("status") == "error" for event in events),
        "remaining": max(0, total - len(latest)), "active": list(active.values()),
        "per_model": per_model, "tokens": tokens, "estimated_seconds_remaining": eta,
        "pid": pid, "process_alive": alive, "last_event_at": heartbeat,
        "collector_lock_held": locked, "last_activity_age_seconds": round(age, 1) if age is not None else None,
        "interrupted_tasks": interrupted_tasks,
        "supervisor_running": supervisor_locked is True, "supervisor": supervisor_event,
        "query_date": manifest["config"]["query_date"],
        "streamed_bytes": sum(path.stat().st_size for path in (directory / "raw").glob("*.sse")),
    }


def render(status):
    rows = [
        f"状态：{status['state_text']}　进度：{status['completed']}/{status['total']}　请求尝试：{status['attempts']}",
        f"有正文与来源：{status['ok']}　待核：{status['needs_review']}　接口失败：{status['error']}　剩余：{status['remaining']}",
    ]
    for alias, counts in status["per_model"].items():
        done = sum(counts[key] for key in ("ok", "needs_review", "error"))
        rows.append(f"  {alias:8} {done}/{counts['total']}　待核{counts['needs_review']}　失败{counts['error']}")
    current = ", ".join(item["task_id"] + "/" + item["model"] for item in status["active"]) or "无"
    rows.append("当前请求：" + current)
    rows.append(f"最后活动：{status['last_event_at']}　守护：{'运行中' if status['supervisor_running'] else '未运行'}")
    eta = status["estimated_seconds_remaining"]
    estimate = ("暂停" if status["state"] not in ("pilot", "collecting") else "估算中") if eta is None else f"约{eta // 60}分{eta % 60}秒"
    rows.append(f"预计剩余：{estimate}　已记录Tokens：{status['tokens']}　流数据：{status['streamed_bytes'] // 1024}KB")
    if status["reason"]:
        rows.append("说明：" + status["reason"])
    rows.append("结果：" + status["directory"])
    return "\n".join(rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, help="指定采集目录；默认选择最近一次批量采集")
    parser.add_argument("--root", type=Path, default=api.HERE / "outputs")
    parser.add_argument("--watch", action="store_true", help="持续刷新；Ctrl+C只退出监控")
    parser.add_argument("--interval", type=float, default=5)
    parser.add_argument("--json", action="store_true", help="输出机器可读的进度JSON")
    parser.add_argument("--stop", action="store_true", help="请求停止新增任务，正在进行的请求先保存")
    args = parser.parse_args(argv)
    if args.interval < 1:
        parser.error("--interval至少1秒")
    directory = args.run.resolve() if args.run else latest_run(args.root)
    if args.stop:
        batch.append_json(directory / "control.jsonl", {"action": "stop", "time": api.now_beijing().isoformat()})
        print("停止请求已写入；正在进行的请求会先保存结果。")
        return 0
    while True:
        status = snapshot(directory)
        if args.watch and sys.stdout.isatty() and not args.json:
            print("\033[2J\033[H", end="")
        print(json.dumps(status, ensure_ascii=False, indent=2) if args.json else render(status), flush=True)
        if not args.watch or status["state"] in ("completed", "completed_with_errors"):
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已退出监控；后台采集继续运行。")
    except (ValueError, OSError) as error:
        print("监控错误：" + str(error), file=sys.stderr)
        sys.exit(2)
