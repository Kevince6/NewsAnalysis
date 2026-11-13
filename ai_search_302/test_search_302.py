"""离线测试；HTTP请求均被替换，不调用302，不消耗额度。测试文件保留在.test_runs。"""

import contextlib
import io
import json
import os
from pathlib import Path
from datetime import datetime
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import URLError
from uuid import uuid4

import search_302 as app


class SearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = app.HERE / ".test_runs" / uuid4().hex
        cls.root.mkdir(parents=True, exist_ok=False)
        cls.config = app.load_config(app.HERE / "config.json")
        cls.catalog = {"data": [{"id": value} for value in cls.config["models"].values()]}

    def test_sources_keep_original_citation_numbers_and_duplicates(self):
        response = {"citations": ["https://example.com/a", None, "https://example.com/a"]}
        sources = app.extract_sources(response, {})
        self.assertEqual([row["index"] for row in sources], [1, 3])
        self.assertEqual(sources[0]["url"], sources[1]["url"])

    def test_annotations_keep_text_offsets(self):
        sources = app.extract_sources({}, {"annotations": [{
            "type": "url_citation",
            "url_citation": {"url": "https://example.com/b", "title": "来源", "start_index": 2, "end_index": 8},
        }]})
        self.assertEqual(sources[0]["start_index"], 2)
        self.assertIsNone(sources[0]["index"])

    def test_malformed_source_does_not_discard_the_answer(self):
        result = app.normalize({
            "citations": ["https://[broken", "javascript:alert(1)"],
            "choices": [{"message": {"content": "仍然保留这段回答"}, "finish_reason": "stop"}],
        })
        self.assertEqual(result["answer"], "仍然保留这段回答")
        self.assertEqual(result["sources"], [])
        self.assertEqual(result["status"], "needs_review")

    def test_body_urls_are_not_reported_as_platform_sources(self):
        result = app.normalize({"choices": [{
            "message": {"content": "据https://example.com/model-invented所述……"},
            "finish_reason": "stop",
        }]})
        self.assertEqual(result["sources"], [])
        self.assertEqual(result["status"], "needs_review")

    def test_truncation_and_refusal_are_flagged(self):
        for choice in (
            {"message": {"content": "未完成"}, "finish_reason": "length"},
            {"message": {"content": "不能回答", "refusal": "refused"}, "finish_reason": "stop"},
        ):
            result = app.normalize({"citations": ["https://example.com"], "choices": [choice]})
            self.assertEqual(result["status"], "needs_review")

    def test_actual_request_parameters_and_transport(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b'{"id":"test-response"}'
        response.headers = {"request-id": "request-test"}
        opener = MagicMock()
        opener.open.return_value = response
        payload = app.build_payload(self.config, "qwen", "原始问题")
        with patch.object(app, "build_opener", return_value=opener):
            result, request_id = app.api_request(
                self.config["base_url"], "/chat/completions", "test-key", 30, payload,
            )
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer test-key")
        body = json.loads(request.data)
        self.assertTrue(body["web-search"])
        self.assertEqual(body["search-service"], "metaso")
        self.assertNotIn("response_format", body)
        self.assertEqual(body["messages"][-1]["content"], "原始问题")
        self.assertEqual(request_id, "request-test")
        self.assertEqual(result["id"], "test-response")

    def test_network_failure_is_not_retried(self):
        opener = MagicMock()
        opener.open.side_effect = URLError("mock timeout")
        with patch.object(app, "build_opener", return_value=opener):
            with self.assertRaises(app.APIError):
                app.api_request(self.config["base_url"], "/chat/completions", "test-key", 30, {})
        self.assertEqual(opener.open.call_count, 1)

    def test_cards_only_send_questions(self):
        path = self.root / "cards_fixture.json"
        app.save_json(path, [{
            "id": 17, "summary": "PRIVATE_GOLD_SUMMARY", "facts": ["PRIVATE_GOLD_FACT"],
            "sources": ["https://gold.example.com"],
            "questions": ["【事实】演出是哪天？", "【开放】争议是什么？"],
        }])
        tasks = app.load_questions(path, 1)
        payload = app.build_payload(self.config, "doubao", tasks[0]["question"])
        self.assertEqual(payload["messages"][-1]["content"], "演出是哪天？")
        self.assertNotIn("PRIVATE_GOLD", json.dumps(payload))
        self.assertNotIn("gold.example.com", json.dumps(payload))
        self.assertEqual(tasks[0]["question_original"], "【事实】演出是哪天？")

    def test_dry_run_never_reads_key_or_calls_network(self):
        capture = io.StringIO()
        with patch.dict(os.environ, {"AI302_API_KEY": ""}):
            with patch.object(app, "api_request") as api, contextlib.redirect_stdout(capture):
                code = app.main(["--prompt", "新闻问题", "--dry-run"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(capture.getvalue())["planned_calls"], 3)
        api.assert_not_called()

    def test_prompt_file_is_resolved_relative_to_config(self):
        fixture = self.root / "custom_prompt"
        fixture.mkdir()
        (fixture / "custom.txt").write_text("这是独立的公共提示词。", encoding="utf-8")
        config = json.loads((app.HERE / "config.json").read_text(encoding="utf-8"))
        config["system_prompt_file"] = "custom.txt"
        app.save_json(fixture / "config.json", config)
        loaded = app.load_config(fixture / "config.json")
        self.assertEqual(loaded["system_prompt"], "这是独立的公共提示词。")

    def test_missing_prompt_file_stops_before_network(self):
        fixture = self.root / "missing_prompt_config.json"
        config = json.loads((app.HERE / "config.json").read_text(encoding="utf-8"))
        config["system_prompt_file"] = "does_not_exist.txt"
        app.save_json(fixture, config)
        with patch.object(app, "api_request") as api:
            with self.assertRaises(FileNotFoundError):
                app.main(["--config", str(fixture), "--prompt", "问题"])
        api.assert_not_called()

    def test_models_get_identical_independent_messages(self):
        first = [
            app.build_payload(self.config, alias, "第一个问题")
            for alias in app.ALIASES
        ]
        self.assertTrue(all(item["messages"] == first[0]["messages"] for item in first))
        second = app.build_payload(self.config, "qwen", "第二个问题")
        self.assertEqual(len(second["messages"]), 2)
        self.assertEqual(second["messages"][-1]["content"], "第二个问题")
        self.assertNotIn("第一个问题", json.dumps(second, ensure_ascii=False))

    def test_run_date_is_frozen_for_messages_across_midnight(self):
        before = datetime(2026, 11, 14, 23, 59, tzinfo=app.BEIJING)
        after = datetime(2026, 11, 15, 0, 1, tzinfo=app.BEIJING)
        with patch.object(app, "now_beijing", return_value=before):
            config = app.load_config(app.HERE / "config.json")
        with patch.object(app, "now_beijing", return_value=after):
            bodies = [app.build_payload(config, alias, "现在的情况？") for alias in app.ALIASES]
        self.assertEqual(config["query_date"], "2026-11-14")
        self.assertTrue(all("2026-11-14" in body["messages"][0]["content"] for body in bodies))

    def test_date_override_and_invalid_date(self):
        capture = io.StringIO()
        with patch.object(app, "api_request") as api, contextlib.redirect_stdout(capture):
            code = app.main(["--prompt", "新闻问题", "--dry-run", "--query-date", "2026-11-14"])
            with self.assertRaises(ValueError):
                app.main(["--prompt", "新闻问题", "--query-date", "2026-02-30"])
        plan = json.loads(capture.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(plan["query_date"], "2026-11-14")
        self.assertTrue(all("2026-11-14" in row["body"]["messages"][0]["content"] for row in plan["requests"]))
        api.assert_not_called()

    def test_missing_model_stops_before_paid_calls(self):
        capture = io.StringIO()
        with patch.dict(os.environ, {"AI302_API_KEY": "mock-secret-not-real"}):
            with patch.object(app, "api_request", return_value=({"data": []}, None)) as api:
                with contextlib.redirect_stdout(capture):
                    code = app.main(["--prompt", "新闻问题", "--output", str(self.root / "missing")])
        self.assertEqual(code, 1)
        self.assertEqual(api.call_count, 1)

    def test_success_records_answer_and_sources_without_saving_key(self):
        response = {
            "id": "completion-test", "model": "actual-model",
            "citations": ["https://example.com/official"],
            "choices": [{"message": {"content": "自然语言回答[1]"}, "finish_reason": "stop"}],
            "usage": {"total_tokens": 25},
        }
        capture = io.StringIO()
        output = self.root / "success"
        secret = "mock-secret-not-real"
        with patch.dict(os.environ, {"AI302_API_KEY": secret}):
            with patch.object(app, "api_request", side_effect=[
                (self.catalog, None), (response, "request-test"),
            ]) as api:
                with contextlib.redirect_stdout(capture):
                    code = app.main(["--prompt", "新闻问题", "--models", "qwen", "--output", str(output)])
        self.assertEqual(code, 0)
        self.assertEqual(api.call_count, 2)
        result_path = next(output.glob("*/0001_qwen.json"))
        result = json.loads(result_path.read_text(encoding="utf-8"))
        self.assertEqual(result["answer"], "自然语言回答[1]")
        self.assertEqual(result["sources"][0]["url"], "https://example.com/official")
        self.assertEqual(result["request_id"], "request-test")
        run = json.loads((result_path.parent / "run.json").read_text(encoding="utf-8"))
        raw = json.loads((result_path.parent / result["raw_file"]).read_text(encoding="utf-8"))
        self.assertEqual(run["system_message"], raw["request"]["messages"][0]["content"])
        self.assertEqual(run["prompt_sha256"], result["prompt_sha256"])
        self.assertEqual(result["prompt_version"], "news-search-v1")
        self.assertTrue(result["requested_at"].endswith("+08:00"))
        for path in output.rglob("*.json"):
            self.assertNotIn(secret, path.read_text(encoding="utf-8"))

    def test_auth_error_stops_and_redacts_error_response(self):
        secret = "mock-secret-not-real"
        output = self.root / "auth"
        capture = io.StringIO()
        error = app.APIError("bad " + secret, status=401, response={"error": "bad " + secret})
        with patch.dict(os.environ, {"AI302_API_KEY": secret}):
            with patch.object(app, "api_request", side_effect=[(self.catalog, None), error]) as api:
                with contextlib.redirect_stdout(capture):
                    code = app.main(["--prompt", "新闻问题", "--output", str(output)])
        self.assertEqual(code, 1)
        self.assertEqual(api.call_count, 2)
        self.assertNotIn(secret, capture.getvalue())
        for path in output.rglob("*.json"):
            self.assertNotIn(secret, path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
