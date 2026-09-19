#!/usr/bin/env python3
"""Lab 5: store the frozen corpus in the official mcp-server-qdrant's collection.

eval.py fills abox-nomic for retrieval-agent-nomic. retrieval-agent reads
abox-minilm through the official server, which embeds with its own MiniLM, so
it needs the same 135 texts stored through that server's own tool.

  kubectl -n kagent port-forward svc/qdrant-mcp-official 3001:3000
  uv run docs/labs/05/scripts/ingest_official.py
"""

from __future__ import annotations

import asyncio
import importlib.util
from collections import Counter
from pathlib import Path

import requests

from mcp import Client

URL = "http://127.0.0.1:3001/mcp"
COLLECTION_URL = "http://127.0.0.1:6333/collections/abox-minilm"

spec = importlib.util.spec_from_file_location("lab05_eval", Path(__file__).with_name("eval.py"))
assert spec is not None and spec.loader is not None
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


def stored_documents() -> Counter[tuple[str, str, str, str]]:
    """Read every page; never silently append to a different or duplicated corpus."""
    actual: Counter[tuple[str, str, str, str]] = Counter()
    offset = None
    while True:
        body = {"limit": 256, "with_payload": True, "with_vector": False}
        if offset is not None:
            body["offset"] = offset
        response = requests.post(COLLECTION_URL + "/points/scroll", json=body, timeout=30)
        if response.status_code == 404 and offset is None:
            return actual
        response.raise_for_status()
        result = response.json()["result"]
        for point in result["points"]:
            payload = point["payload"]
            meta = payload["metadata"]
            actual[(meta["kind"], meta["name"], meta["repo"], payload["document"])] += 1
        offset = result.get("next_page_offset")
        if offset is None:
            return actual


def missing_documents(docs: list[dict[str, str]], actual: Counter[tuple[str, str, str, str]]) -> list[dict[str, str]]:
    expected = Counter((d["kind"], d["name"], d["repo"], d["text"]) for d in docs)
    if actual - expected:
        raise ValueError("Official collection has unexpected, changed or duplicate documents; no writes made")
    remaining = expected - actual
    return [d for d in docs if (d["kind"], d["name"], d["repo"], d["text"]) in remaining]


async def main() -> None:
    entries, _ = evaluation.load()
    docs = evaluation.documents(entries)
    missing = missing_documents(docs, stored_documents())
    if not missing:
        print(f"verified {len(docs)} documents; stored 0 (already complete)")
        return
    async with Client(URL, read_timeout_seconds=300) as session:
        for doc in missing:
            metadata = {key: doc[key] for key in ("name", "kind", "repo")}
            result = await session.call_tool("qdrant-store", {"information": doc["text"], "metadata": metadata})
            if result.is_error:
                raise SystemExit(f"qdrant-store failed on {doc['name']}: {evaluation.text_of(result)}")
    if missing_documents(docs, stored_documents()):
        raise ValueError("Official collection is incomplete after ingestion")
    print(f"stored {len(missing)} documents through {URL}; verified all {len(docs)}")


if __name__ == "__main__":
    asyncio.run(main())
