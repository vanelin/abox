"""Regression tests for biased report selection and misleading scoring."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("summary", Path(__file__).resolve().parents[1] / "scripts/summarise.py")
assert spec is not None and spec.loader is not None
summary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(summary)


def row(repetition=1, error=None):
    return {"id": "l01", "repeat": repetition, "error": error, "trace_error": None, "answer": "answer"}


class SummaryTests(unittest.TestCase):
    def test_retry_after_failure_retains_success(self):
        success = row()
        self.assertEqual(summary.select_attempts([row(error="429"), success]), {("l01", 1): success})

    def test_cannot_cherry_pick_after_a_success(self):
        with self.assertRaisesRegex(ValueError, "after success"):
            summary.select_attempts([row(), row()])

    def test_repetitions_are_not_folded(self):
        self.assertEqual(len(summary.select_attempts([row(), row(2)])), 2)

    def test_unresolved_failure_is_not_dropped(self):
        selected = summary.select_attempts([row(error="429")])
        self.assertTrue(summary.failed(selected[("l01", 1)]))

    def test_missing_usage_is_unknown_not_zero(self):
        self.assertIsNone(summary.tokens({"usage_events": []}))
        self.assertEqual(summary.tokens({"usage_events": [{"promptTokenCount": 3, "candidatesTokenCount": 2}]}), 5)

    def test_seed_read_without_edges_is_not_traversal(self):
        call = {"name": "get_graph_node", "args": {"qn": "map::Helm"}, "response": {"output": "{}"}}
        self.assertEqual(summary.graph_method({"tool_calls": [call]}, "Helm"), "other")
        call["response"]["output"] = json.dumps({"references_by": ["map::kbot"]})
        self.assertEqual(summary.graph_method({"tool_calls": [call]}, "Helm"), "incoming_edges")

    def test_verdict_is_invalidated_by_changed_answer_or_trace(self):
        original = row() | {"tool_calls": []}
        self.assertNotEqual(summary.row_digest(original), summary.row_digest(original | {"answer": "different"}))
        self.assertNotEqual(summary.row_digest(original), summary.row_digest(original | {"tool_calls": ["new"]}))

    def test_stale_judgement_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "review.json"
            path.write_text(json.dumps({"rows": {"stale-hash": {}}}))
            with self.assertRaisesRegex(ValueError, "Stale judgement"):
                summary.load_judgements(path, {})

    def test_campaign_rejects_changed_raw_report(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "corpus.json").write_text("{}")
            question = {"id": "l01", "question": "Where?", "gold": ["kbot"], "type": "lookup", "language": "en"}
            dataset = {"corpus": "corpus.json", "corpus_sha256": summary.digest(b"{}"), "questions": [question]}
            question_bytes = json.dumps(dataset).encode()
            (root / "questions.json").write_bytes(question_bytes)
            reports = {}
            for agent in summary.AGENTS:
                answer = row() | question
                report = {
                    "agent": "retrieval-agent" + ("" if agent == "official" else f"-{agent}"),
                    "run_id": "20260919",
                    "corpus_sha256": dataset["corpus_sha256"],
                    "rows": [answer],
                }
                raw = json.dumps(report).encode()
                (root / f"{agent}.json").write_bytes(raw)
                reports[agent] = [{"path": f"{agent}.json", "sha256": summary.digest(raw)}]
            manifest = {
                "questions": "questions.json",
                "questions_sha256": summary.digest(question_bytes),
                "reports": reports,
                "repeat": 1,
            }
            path = root / "campaign.json"
            path.write_text(json.dumps(manifest))
            with patch.object(summary, "ROOT", root):
                _, _, agents = summary.load_campaign(path)
                self.assertEqual(len(agents), 3)
                (root / "xray.json").write_text("{}")
                with self.assertRaisesRegex(ValueError, "Raw report changed"):
                    summary.load_campaign(path)
                (root / "questions.json").write_text("{}")
                with self.assertRaisesRegex(ValueError, "Questions changed"):
                    summary.load_campaign(path)


if __name__ == "__main__":
    unittest.main()
