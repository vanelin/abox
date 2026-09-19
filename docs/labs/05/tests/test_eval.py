"""Regression checks for comparable retrieval scoring; no network or cluster."""

import asyncio
import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location("lab05_eval", Path(__file__).resolve().parents[1] / "scripts/eval.py")
assert spec is not None and spec.loader is not None
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


class ScoringTests(unittest.TestCase):
    def test_both_backends_filter_non_repos_and_credit_sections_identically(self):
        prefix = "vanelin//catalog::"
        xray = {"results": []}
        qdrant = []
        for kind, name, repo, score in [
            ("Topic", "GitOps", "", 0.99),
            ("Section", "one.Intro", "one", 0.9),
            ("Repo", "one", "one", 0.8),
            ("Language", "Go", "", 0.75),
            ("Repo", "two", "two", 0.7),
        ]:
            hit = {"kind": kind, "qn": prefix + name, "score": score}
            if kind == "Section":
                hit["parent"] = prefix + repo
            xray["results"].append(hit)
            qdrant.append({"score": score, "payload": {"kind": kind, "name": name, "repo": repo}})
        repos = {"one", "two"}
        self.assertEqual(evaluation.xray_repos(xray, prefix, repos, True), (["one", "two"], 0.9))
        self.assertEqual(evaluation.qdrant_repos(qdrant, repos), (["one", "two"], 0.9))

    def test_mrr_does_not_credit_rank_six(self):
        result = evaluation.ranked_score(["a", "b", "c", "d", "e", "answer"], ["answer"])
        self.assertEqual(result["rr"], 0)
        self.assertEqual(result["recall"], 0)

    def test_multi_answer_recall(self):
        result = evaluation.ranked_score(["wrong", "one"], ["one", "two"])
        self.assertEqual(result["recall"], 0.5)
        self.assertEqual(result["rr"], 0.5)

    def test_malformed_responses_are_not_scored_as_misses(self):
        with self.assertRaises(ValueError):
            evaluation.xray_repos({"error": "timeout"}, "prefix", {"one"}, True)
        with self.assertRaises(ValueError):
            evaluation.qdrant_repos({"error": "timeout"}, {"one"})

    def test_mcp_error_stops_evaluation(self):
        class Session:
            async def call_tool(self, tool, args):
                return SimpleNamespace(is_error=True, content=[SimpleNamespace(type="text", text="failed")])

        with self.assertRaisesRegex(RuntimeError, "failed"):
            asyncio.run(evaluation.call(Session(), "search_graph", {}))

    def test_invalid_json_stops_evaluation(self):
        class Session:
            async def call_tool(self, tool, args):
                return SimpleNamespace(is_error=False, content=[SimpleNamespace(type="text", text="not JSON")])

        with self.assertRaises(ValueError):
            asyncio.run(evaluation.call(Session(), "search_graph", {}))


if __name__ == "__main__":
    unittest.main()
