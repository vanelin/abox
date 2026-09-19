"""A second ingestion must not duplicate or silently mix corpora."""

import importlib.util
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location(
    "official", Path(__file__).resolve().parents[1] / "scripts/ingest_official.py"
)
assert spec is not None and spec.loader is not None
official = importlib.util.module_from_spec(spec)
spec.loader.exec_module(official)
DOC = {"kind": "Repo", "name": "kbot", "repo": "kbot", "text": "Telegram bot"}
KEY = ("Repo", "kbot", "kbot", "Telegram bot")


class OfficialTests(unittest.TestCase):
    def test_complete_is_noop_and_partial_resumes(self):
        self.assertEqual(official.missing_documents([DOC], Counter({KEY: 1})), [])
        self.assertEqual(official.missing_documents([DOC], Counter()), [DOC])

    def test_duplicates_and_changed_documents_are_refused(self):
        for actual in [Counter({KEY: 2}), Counter({KEY[:-1] + ("different text",): 1})]:
            with self.subTest(actual=actual), self.assertRaises(ValueError):
                official.missing_documents([DOC], actual)

    def test_scroll_checks_every_page(self):
        payload = {"metadata": {k: DOC[k] for k in ("kind", "name", "repo")}, "document": DOC["text"]}
        first = Mock(status_code=200)
        first.json.return_value = {"result": {"points": [{"payload": payload}], "next_page_offset": "cursor"}}
        second = Mock(status_code=200)
        second.json.return_value = {"result": {"points": [{"payload": payload}], "next_page_offset": None}}
        with patch.object(official.requests, "post", side_effect=[first, second]) as post:
            self.assertEqual(official.stored_documents(), Counter({KEY: 2}))
        self.assertEqual(post.call_args.kwargs["json"]["offset"], "cursor")


if __name__ == "__main__":
    unittest.main()
