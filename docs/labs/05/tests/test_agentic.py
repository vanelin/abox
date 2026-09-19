"""Offline checks for A2A parsing, trace collection and evaluator isolation."""

import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "lab05_agentic", Path(__file__).resolve().parents[1] / "scripts/agentic.py"
)
assert spec is not None and spec.loader is not None
agentic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agentic)


class AgenticTests(unittest.TestCase):
    def test_new_message_has_no_gold_or_context(self):
        task = {"result": {"kind": "task", "status": {"state": "completed"}}}
        with patch.object(agentic, "rpc", return_value=task) as rpc:
            agentic.send("http://example.invalid", "Where is my bot?", 10)
            first = rpc.call_args.args[2]["message"]
            agentic.send("http://example.invalid", "Where is my bot?", 10)
            second = rpc.call_args.args[2]["message"]
        self.assertEqual(first["parts"], [{"kind": "text", "text": "Where is my bot?"}])
        self.assertEqual(set(first), {"kind", "role", "messageId", "parts"})
        self.assertNotEqual(first["messageId"], second["messageId"])

    def test_working_task_is_polled(self):
        working = {"result": {"kind": "task", "id": "t1", "status": {"state": "working"}}}
        completed = {"result": {"kind": "task", "id": "t1", "status": {"state": "completed"}}}
        with patch.object(agentic, "rpc", side_effect=[working, completed]) as rpc, patch.object(agentic.time, "sleep"):
            replies = agentic.send("http://example.invalid", "Question", 10)
        self.assertEqual(len(replies), 2)
        self.assertEqual(rpc.call_args.args[1:3], ("tasks/get", {"id": "t1"}))

    def test_input_required_is_not_approved_automatically(self):
        response = {"result": {"kind": "task", "status": {"state": "input-required"}}}
        with patch.object(agentic, "rpc", return_value=response) as rpc:
            self.assertEqual(agentic.send("http://example.invalid", "Question", 10), [response])
        self.assertEqual(rpc.call_count, 1)

    def test_answer_uses_final_artifact_not_intermediate_text(self):
        task = {
            "kind": "task",
            "artifacts": [{"parts": [{"kind": "text", "text": "kbot"}]}],
            "history": [{"role": "agent", "parts": [{"kind": "text", "text": "Searching..."}]}],
        }
        self.assertEqual(agentic.answer_text(task), "kbot")
        del task["artifacts"]
        task["history"].append({"role": "agent", "parts": [{"kind": "text", "text": "Final answer"}]})
        self.assertEqual(agentic.answer_text(task), "Final answer")

    def test_trace_joins_by_call_id_and_deduplicates_events(self):
        call = {"id": "call-1", "name": "get_graph_impact", "args": {"depth": 1, "seeds": ["Terraform"]}}
        event = {
            "id": "event-1",
            "data": json.dumps(
                {"Content": {"parts": [{"functionCall": call}]}, "UsageMetadata": {"promptTokenCount": 5}}
            ),
        }
        response = {
            "id": "event-2",
            "data": {"Content": {"parts": [{"functionResponse": {"id": "call-1", "response": {"count": 5}}}]}},
        }
        trace = agentic.parse_trace([event, event, response])
        self.assertEqual(len(trace["tool_calls"]), 1)
        self.assertEqual(trace["tool_calls"][0]["args"], call["args"])
        self.assertEqual(trace["tool_calls"][0]["response"], {"count": 5})
        self.assertEqual(len(trace["usage_events"]), 1)

    def test_missing_events_are_not_zero_tool_calls(self):
        with self.assertRaises(ValueError):
            agentic.parse_trace([])

    def test_mention_check_is_not_a_correctness_judge(self):
        result = agentic.mention_check(
            "The answer is not kbot; kbot-extra is unrelated.", ["kbot", "omni"], ["kbot"], False
        )
        self.assertEqual(result["mentioned"], ["kbot"])
        self.assertTrue(result["requires_human_review"])
        self.assertNotIn("correct", result)
        self.assertEqual(agentic.mention_check("kbot-extra", ["kbot"], ["kbot"], False)["mentioned"], [])


if __name__ == "__main__":
    unittest.main()
