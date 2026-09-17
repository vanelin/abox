#!/usr/bin/env python3
"""Lab 4: score a Qdrant MCP toolset on the lab 3 corpus.

Talks to an MCPServer the way an agent does -- through kmcp's streamable HTTP
endpoint, calling its store and find tools -- but deterministically: every
chunk from docs/labs/03/chunks.jsonl is stored once with its id in the
metadata, every question from docs/labs/03/questions.json is searched once,
and hit@1 / hit@3 are computed from the ids that come back. That isolates the
toolset (tool contract + embedding model + collection) from the model driving
the agent; the agentic pass is separate, see README.md.

Three toolsets are known:

  official  qdrant/mcp-server-qdrant, fastembed all-MiniLM-L6-v2, 384 dims
            tools qdrant-store / qdrant-find, MCPServer qdrant-mcp-official
  nomic     our Go qdrant-mcp, nomic-embed-text-v1.5 over llama.cpp, 768 dims
            tools vector_store / vector_find, MCPServer qdrant-mcp
  qwen      the same Go qdrant-mcp on Qwen3-Embedding-0.6B Q8_0, 256 of 1024
            dims (EMBEDDINGS_DIMS), MCPServer qdrant-mcp-qwen

Port-forward the MCPServer Service first (kmcp serves /mcp on port 3000):

  kubectl -n kagent port-forward svc/qdrant-mcp-official 3001:3000
  kubectl -n kagent port-forward svc/qdrant-mcp 3002:3000
  kubectl -n kagent port-forward svc/qdrant-mcp-qwen 3003:3000

  uv run docs/labs/04/eval.py official --ingest
  uv run docs/labs/04/eval.py nomic --ingest
  uv run docs/labs/04/eval.py qwen --ingest
  uv run docs/labs/04/eval.py official            # search only, corpus already stored

Storing is not idempotent on either server (each call mints new point ids), so
--ingest into a non-empty collection duplicates it. --reset drops the collection
first through Qdrant's REST API (port-forward svc/qdrant 6333 in namespace qdrant).
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import hashlib
import json
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import requests

from mcp import Client

ROOT = Path(__file__).resolve().parents[3]
LAB3 = ROOT / "docs" / "labs" / "03"
OUT_DIR = ROOT / ".local" / "lab04"

TOOLSETS: dict[str, dict[str, Any]] = {
    "official": {
        "url": "http://127.0.0.1:3001/mcp",
        "store": "qdrant-store",
        "find": "qdrant-find",
        "collection": "abox-minilm",
        "model": "sentence-transformers/all-MiniLM-L6-v2 (fastembed)",
        "server": "qdrant-mcp-official",
    },
    "nomic": {
        "url": "http://127.0.0.1:3002/mcp",
        "store": "vector_store",
        "find": "vector_find",
        "collection": "abox-nomic",
        "model": "nomic-embed-text-v1.5 (llama.cpp)",
        "server": "qdrant-mcp",
    },
    "qwen": {
        "url": "http://127.0.0.1:3003/mcp",
        "store": "vector_store",
        "find": "vector_find",
        "collection": "abox-qwen256",
        "model": "Qwen3-Embedding-0.6B Q8_0, 256 dims (llama.cpp)",
        "server": "qdrant-mcp-qwen",
    },
}

ENTRY_RE = re.compile(r"<entry><content>(.*?)</content><metadata>(.*?)</metadata></entry>", re.S)


def load_corpus() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    questions = json.loads((LAB3 / "questions.json").read_text())
    corpus_path = LAB3 / questions["corpus"]
    digest = hashlib.sha256(corpus_path.read_bytes()).hexdigest()
    if digest != questions["corpus_sha256"]:
        raise SystemExit(
            f"{corpus_path} sha256 {digest} != questions.json corpus_sha256; inputs are not the frozen set"
        )
    chunks = [json.loads(line) for line in corpus_path.read_text().splitlines() if line.strip()]
    return chunks, questions["questions"]


def text_of(result: Any) -> str:
    parts = []
    for block in result.content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "\n".join(parts)


def parse_hits(toolset: str, text: str) -> list[dict[str, Any]]:
    """Return hits as [{'id': chunk id or None, 'metadata': {...}}] best first."""
    if toolset in ("nomic", "qwen"):
        # JSON list of {score, payload}; payload carries our metadata flat.
        hits = json.loads(text) if text.strip().startswith("[") else []
        return [{"id": h.get("payload", {}).get("id"), "metadata": h.get("payload", {})} for h in hits]
    # official: "<entry><content>..</content><metadata>{json or python dict}</metadata></entry>" per result
    # FastMCP returns the server's list[str] as one text block holding the JSON list, so unwrap it first.
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        decoded = None
    if isinstance(decoded, list):
        text = "\n".join(item for item in decoded if isinstance(item, str))
    out = []
    for _content, meta in ENTRY_RE.findall(text):
        meta = meta.strip()
        parsed: Any = {}
        if meta:
            try:
                parsed = json.loads(meta)
            except json.JSONDecodeError:
                try:
                    parsed = ast.literal_eval(meta)
                except (ValueError, SyntaxError):
                    parsed = {}
        out.append({"id": parsed.get("id") if isinstance(parsed, dict) else None, "metadata": parsed})
    return out


def reset_collection(qdrant: str, collection: str) -> None:
    r = requests.delete(f"{qdrant}/collections/{collection}", timeout=30)
    if r.status_code not in (200, 404):
        raise SystemExit(f"DELETE {collection}: {r.status_code} {r.text}")
    print(f"dropped collection {collection} ({r.status_code})")


async def run(args: argparse.Namespace) -> int:
    ts = TOOLSETS[args.toolset]
    url = args.url or ts["url"]
    chunks, questions = load_corpus()

    if args.reset:
        if not args.qdrant:
            raise SystemExit("--reset needs --qdrant http://127.0.0.1:6333")
        reset_collection(args.qdrant, ts["collection"])

    async with Client(url, read_timeout_seconds=300) as session:
        tools = {t.name for t in (await session.list_tools()).tools}
        for name in (ts["store"], ts["find"]):
            if name not in tools:
                raise SystemExit(f"{url} serves {sorted(tools)}, not {name}; wrong port-forward for '{args.toolset}'?")

        ingest_s = None
        if args.ingest:
            t0 = time.perf_counter()
            for i, c in enumerate(chunks, 1):
                meta = {
                    "id": c["id"],
                    "path": c["path"],
                    "kind": c["kind"],
                    "start": str(c["start"]),
                    "end": str(c["end"]),
                }
                res = await session.call_tool(ts["store"], {"information": c["text"], "metadata": meta})
                if res.is_error:
                    raise SystemExit(f"{ts['store']} failed on {c['id']}: {text_of(res)}")
                if i % 20 == 0 or i == len(chunks):
                    print(f"stored {i}/{len(chunks)}", file=sys.stderr)
            ingest_s = round(time.perf_counter() - t0, 1)

        per_q = []
        latencies = []
        for q in questions:
            t0 = time.perf_counter()
            res = await session.call_tool(ts["find"], {"query": q["question"]})
            latencies.append(time.perf_counter() - t0)
            if res.is_error:
                raise SystemExit(f"{ts['find']} failed on {q['id']}: {text_of(res)}")
            hits = parse_hits(args.toolset, text_of(res))
            ids = [h["id"] for h in hits]
            relevant = set(q["relevant_ids"])
            per_q.append(
                {
                    "id": q["id"],
                    "language": q["language"],
                    "question": q["question"],
                    "relevant_ids": q["relevant_ids"],
                    "top": ids[:5],
                    "hit1": bool(ids[:1]) and ids[0] in relevant,
                    "hit3": any(i in relevant for i in ids[:3]),
                    "unparsed": len(hits) == 0,
                }
            )

    n = len(per_q)
    hit1 = sum(r["hit1"] for r in per_q)
    hit3 = sum(r["hit3"] for r in per_q)
    ua = [r for r in per_q if r["language"] == "uk"]
    ua3 = sum(r["hit3"] for r in ua)
    lat = sorted(latencies)
    summary = {
        "toolset": args.toolset,
        "server": ts["server"],
        "model": ts["model"],
        "collection": ts["collection"],
        "chunks": len(chunks),
        "questions": n,
        "ingest_seconds": ingest_s,
        "hit@1": f"{hit1}/{n}",
        "hit@3": f"{hit3}/{n}",
        "uk_hit@3": f"{ua3}/{len(ua)}",
        "find_p50_s": round(statistics.median(lat), 3),
        "find_max_s": round(lat[-1], 3),
        "unparsed_results": sum(r["unparsed"] for r in per_q),
        "date": time.strftime("%Y-%m-%d"),
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"results-{args.toolset}.json"
    out.write_text(json.dumps({"summary": summary, "questions": per_q}, indent=1, ensure_ascii=False) + "\n")

    print(json.dumps(summary, indent=1, ensure_ascii=False))
    for r in per_q:
        mark = "1" if r["hit1"] else ("3" if r["hit3"] else "-")
        print(f"{r['id']} [{mark}] {r['top'][:3]}")
    print(f"written {out.relative_to(ROOT)}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("toolset", choices=sorted(TOOLSETS))
    p.add_argument("--url", help="MCP endpoint; default is the toolset's port-forward URL")
    p.add_argument("--ingest", action="store_true", help="store every corpus chunk before searching")
    p.add_argument("--reset", action="store_true", help="drop the collection first (needs --qdrant)")
    p.add_argument("--qdrant", help="Qdrant REST URL for --reset, e.g. http://127.0.0.1:6333")
    return asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
