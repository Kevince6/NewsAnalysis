"""采集器离线测试；不访问302、不消耗额度。"""

import contextlib
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

import collect_302 as batch
import credentials_302 as credentials
import monitor_302 as monitor
import search_302 as api


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.root = api.HERE / ".test_runs" / ("batch_" + uuid4().hex)
        self.root.mkdir(parents=True)

    def prepare(self, questions=2):
        cards = self.root / "cards.json"
        api.save_json(cards, [{"id": "E022", "questions": [f"【事实】问题{i}" for i in range(questions)],
                               "facts": ["PRIVATE_GOLD"]}])
        return batch.prepare(cards, api.HERE / "config.json", self.root / "runs")

    def test_key_file_accepts_assignment_and_single_token(self):
        first = self.root / "assignment.env"
        second = self.root / "plain.env"
        first.write_text('AI302_API_KEY="fake-test-key"\n', encoding="utf-8")
        second.write_text("fake-plain-key", encoding="utf-8")
        with patch.dict(os.environ, {"AI302_API_KEY": ""}):
            self.assertEqual(credentials.load_api_key(first), "fake-test-key")
            self.assertEqual(credentials.load_api_key(second), "fake-plain-key")

    def test_prepare_freezes_prompts_and_excludes_gold(self):
        directory = self.prepare()
        tasks = json.loads((directory / "tasks.json").read_text(encoding="utf-8"))
        manifest = json.loads((directory / "collection.json").read_text(encoding="utf-8"))
        self.assertEqual(len(tasks), 6)
        self.assertEqual(len(manifest["pilot_task_ids"]), 3)
        self.assertNotIn("PRIVATE_GOLD", (directory / "tasks.json").read_text(encoding="utf-8"))

    def test_partial_event_line_is_ignored(self):
        path = self.root / "partial_events.jsonl"
        path.write_bytes(b'{"event":"valid"}\n{"event":"unfinished \xe4')
        self.assertEqual(batch.read_events(path), [{"event": "valid"}])

    def test_monitor_stop_is_local_and_reports_dead_process(self):
        directory = self.prepare()
        batch.emit(directory, "state", state="collecting")
        with patch.object(api, "api_request") as request:
            with patch.object(monitor, "process_alive", return_value=False):
                status = monitor.snapshot(directory)
            with contextlib.redirect_stdout(io.StringIO()):
                monitor.main(["--run", str(directory), "--stop"])
        self.assertEqual(status["state"], "interrupted")
        self.assertEqual(status["total"], 6)
        self.assertTrue(batch.stop_requested(directory))
        request.assert_not_called()

    def test_resume_does_not_silently_reissue_uncertain_request(self):
        directory = self.prepare()
        batch.emit(directory, "task_started", task_id="T0001", model="doubao", attempt=1)
        config = api.load_config(api.HERE / "config.json")
        listing = {"data": [{"id": value} for value in config["models"].values()]}
        with patch.object(batch, "load_api_key", return_value="fake-key"):
            with patch.object(api, "api_request", return_value=(listing, None)) as request:
                code = batch.run(directory)
        self.assertEqual(code, 1)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(batch.read_events(directory / "events.jsonl")[-1]["state"], "blocked")

    def test_stop_control_and_single_process_lock(self):
        directory = self.prepare()
        batch.append_json(directory / "control.jsonl", {"action": "stop"})
        self.assertTrue(batch.stop_requested(directory))
        with batch.run_lock(directory / ".collector.lock"):
            with self.assertRaises(ValueError):
                with batch.run_lock(directory / ".collector.lock"):
                    pass
        with batch.run_lock(directory / ".collector.lock"):
            pass

    def test_pilot_failure_stops_before_bulk(self):
        directory = self.prepare()
        config = api.load_config(api.HERE / "config.json")
        listing = {"data": [{"id": value} for value in config["models"].values()]}
        answer = {"model": "test", "choices": [{"message": {"content": "无来源回答"}, "finish_reason": "stop"}]}
        def call(base, path, key, timeout, payload=None):
            return (listing if payload is None else answer), "test-request"
        with patch.object(batch, "load_api_key", return_value="fake-key"):
            with patch.object(api, "api_request", side_effect=call) as request:
                with contextlib.redirect_stdout(io.StringIO()):
                    code = batch.run(directory)
        self.assertEqual(code, 1)
        self.assertEqual(request.call_count, 4)
        self.assertEqual(batch.read_events(directory / "events.jsonl")[-1]["state"], "pilot_failed")

    def test_success_and_resume_do_not_repeat_answers(self):
        directory = self.prepare()
        config = api.load_config(api.HERE / "config.json")
        listing = {"data": [{"id": value} for value in config["models"].values()]}
        def call(base, path, key, timeout, payload=None):
            if payload is None:
                return listing, None
            return {
                "model": payload["model"], "citations": ["https://example.com/source"],
                "choices": [{"message": {"content": "自然回答[1]"}, "finish_reason": "stop"}],
            }, "test-request"
        with patch.object(batch, "load_api_key", return_value="fake-key"):
            with patch.object(api, "api_request", side_effect=call) as request:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(batch.run(directory), 0)
                    self.assertEqual(batch.run(directory), 0)
        self.assertEqual(request.call_count, 8)  # 首次1次列表+6次回答，续跑只查1次列表
        latest, _ = batch.records(directory)
        self.assertEqual(len(latest), 6)
        summary = monitor.snapshot(directory)
        self.assertEqual(summary["completed"], 6)
        self.assertEqual(summary["ok"], 6)
        self.assertTrue(all(value["ok"] == 2 for value in summary["per_model"].values()))
        for path in directory.rglob("*.json"):
            self.assertNotIn("fake-key", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
