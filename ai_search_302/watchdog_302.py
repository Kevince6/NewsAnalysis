"""独立守护采集进程：进程退出后断点续跑；只追加日志，已完成回答不重采。"""

import argparse
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.dont_write_bytecode = True
import collect_302 as batch
import search_302 as api


def log(directory, state, **fields):
    batch.append_json(directory / "supervisor.jsonl", {
        "time": api.now_beijing().isoformat(), "state": state, "pid": os.getpid(), **fields,
    })


def outcome(directory):
    latest, _ = batch.records(directory)
    tasks = json.loads((directory / "tasks.json").read_text(encoding="utf-8"))
    events = batch.read_events(directory / "events.jsonl")
    states = [event for event in events if event.get("event") == "state"]
    state = states[-1].get("state") if states else "prepared"
    auth_error = state == "blocked" and any(record.get("http_status") in (401, 402, 403) for record in latest.values())
    pending = len(tasks) - sum(record.get("status") != "error" for record in latest.values())
    return pending, state, auth_error


def run(directory, max_restarts=3):
    with batch.run_lock(directory / ".supervisor.lock"):
        launched = 0
        child = None
        handles = []
        awake = False
        try:
            if os.name == "nt":
                awake = bool(ctypes.windll.kernel32.SetThreadExecutionState(0x80000001))
            log(directory, "started", prevent_idle_sleep=awake, max_restarts=max_restarts)
            while True:
                if batch.stop_requested(directory):
                    log(directory, "stopped", reason="收到停止指令，不自动重启。")
                    return 0
                locked = batch.lock_held(directory / ".collector.lock")
                if locked is True:
                    log(directory, "watching", child_pid=child.pid if child else None)
                    time.sleep(10)
                    continue
                if locked is None:
                    log(directory, "lock_unknown", reason="无法确认运行锁，未重复启动。")
                    time.sleep(10)
                    continue
                pending, state, auth_error = outcome(directory)
                if pending == 0:
                    log(directory, "completed")
                    return 0
                if auth_error or state in ("waiting_for_key", "pilot_failed"):
                    log(directory, "blocked", reason="需要处理密钥、权限、额度或试采集问题。")
                    return 1
                if launched >= max_restarts:
                    log(directory, "restart_limit", reason="已达到守护重启上限，需要人工检查。")
                    return 1
                if child is not None:
                    child.wait()
                    time.sleep(10)
                launched += 1
                token = api.now_beijing().strftime("%Y%m%d_%H%M%S") + "_" + str(launched)
                stdout = (directory / ("guard_" + token + ".stdout.log")).open("x", encoding="utf-8")
                stderr = (directory / ("guard_" + token + ".stderr.log")).open("x", encoding="utf-8")
                handles.extend([stdout, stderr])
                command = [sys.executable, "-u", "-B", str(api.HERE / "collect_302.py"), "run",
                           str(directory), "--retry-failed"]
                child = subprocess.Popen(
                    command, cwd=str(api.HERE.parent), stdout=stdout, stderr=stderr,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                log(directory, "restarted", child_pid=child.pid, restart=launched, pending=pending)
                # 等新进程取得运行锁，避免启动窗口内重复发起任务。
                for _ in range(30):
                    if child.poll() is not None or batch.lock_held(directory / ".collector.lock"):
                        break
                    time.sleep(1)
                time.sleep(3)
        finally:
            if awake:
                ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
            for handle in handles:
                handle.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--max-restarts", type=int, default=3)
    args = parser.parse_args()
    return run(args.run.resolve(), args.max_restarts)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # 不向日志输出可能包含认证信息的意外异常详情。
        sys.exit(2)
