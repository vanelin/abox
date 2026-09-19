#!/usr/bin/env python3
"""Lab 5: score the memory at the tool level -- no agent, no model, no prompt.

Questions go straight to MCP tools. This compares configured retrieval paths,
not an agent's ability to choose tools or a controlled embedding experiment.

  bash .local/lab05/scripts/forward.sh      # 8085 xray-memory, 3002 qdrant-mcp, 6333 Qdrant

  uv run docs/labs/05/scripts/eval.py xray
  uv run docs/labs/05/scripts/eval.py qdrant --ingest --reset

What is asked, per question type:

  lookup    xray:   search_graph(query), twice -- with no kind (a README
                    section counts for its repository) and with kind=Repo
            qdrant: vector_find(query) over the same 135 node texts
  graph     xray:   get_graph_impact(seed, depth=1), scored as a set, and the
                    same question as a search, to show what a search misses
            qdrant: vector_find(question) -- a vector store has no edges
  facet     xray:   search_graph with the question's attr/order arguments
            qdrant: not applicable, the MCP tool takes no filter
  negative  the top score, for where a "nothing found" threshold would sit

Both plain paths request 20 hits, retain only Repo/Section hits, credit a
Section to its parent and deduplicate before scoring the first five repos.
Graph search is precision/recall at five, independent of the gold set size.
Graph walks and facets receive oracle arguments from the questions file.
Every timed request follows an identical warm-up; timings include MCP and
the full backend path, not just index search. Negative scores are diagnostic,
not a measured abstention accuracy.

Qdrant uses a separate nomic service at 768 dimensions; the xray snapshot
is built at 256 dimensions. These runs do not isolate dimensionality,
prefixes, ranking or caching. Facets are unsupported by this MCP wrapper,
not by Qdrant itself.
Results go to .local/lab05/results-<backend>.json.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import statistics
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

from mcp import Client

ROOT = Path(__file__).resolve().parents[4]
LAB = ROOT / "docs" / "labs" / "05"
OUT_DIR = ROOT / ".local" / "lab05"
XRAY_URL = "http://127.0.0.1:8085/mcp"
QDRANT_MCP_URL = "http://127.0.0.1:3002/mcp"
QDRANT_URL = "http://127.0.0.1:6333"
COLLECTION = "abox-nomic"  # fixed by the qdrant-mcp MCPServer's env
MAP = "vanelin"
K = 5
RAW_LIMIT = 20


def load() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    questions = json.loads((LAB / "data/questions.json").read_text())
    corpus = ROOT / questions["corpus"]
    digest = hashlib.sha256(corpus.read_bytes()).hexdigest()
    if digest != questions["corpus_sha256"]:
        raise SystemExit(f"{corpus} sha256 {digest} != questions.json corpus_sha256; the gold is for another corpus")
    return json.loads(corpus.read_text())["entries"], questions


def text_of(result: Any) -> str:
    return "\n".join(block.text for block in result.content if getattr(block, "type", None) == "text")


async def call(session: Any, tool: str, args: dict[str, Any]) -> tuple[Any, float]:
    started = time.perf_counter()
    result = await session.call_tool(tool, args)
    took = time.perf_counter() - started
    if result.is_error:
        raise RuntimeError(f"MCP tool {tool} failed: {text_of(result)}")
    text = text_of(result)
    try:
        return json.loads(text), took
    except json.JSONDecodeError:
        if tool != "vector_store":
            raise ValueError(f"MCP tool {tool} returned invalid JSON: {text[:200]}") from None
        return text, took


async def measured_call(session: Any, tool: str, args: dict[str, Any]) -> tuple[Any, float]:
    await call(session, tool, args)
    return await call(session, tool, args)


def ranked_score(names: list[str], gold: list[str]) -> dict[str, Any]:
    """names: repositories best first, duplicates already folded."""
    top = names[:K]
    rank = next((i for i, name in enumerate(top, 1) if name in gold), None)
    return {
        "top": top,
        "hit1": bool(top) and top[0] in gold,
        "recall": len(set(top) & set(gold)) / len(gold),
        "rr": 1 / rank if rank else 0.0,
    }


def set_score(names: list[str], gold: list[str]) -> dict[str, Any]:
    found, wanted = set(names), set(gold)
    return {
        "returned": sorted(found),
        "missed": sorted(wanted - found),
        "extra": sorted(found - wanted),
        "precision": len(found & wanted) / len(found) if found else 0.0,
        "recall": len(found & wanted) / len(wanted) if wanted else 1.0,
    }


def fold(names: list[str]) -> list[str]:
    return list(dict.fromkeys(names))


# ---------------------------------------------------------------- xray-memory


def xray_repos(reply: Any, prefix: str, repos: set[str], credit_parent: bool) -> tuple[list[str], float]:
    """Repository names best first. A Section is its repository when credit_parent."""
    if not isinstance(reply, dict) or not isinstance(reply.get("results"), list):
        raise ValueError("search_graph response has no results list")
    results = reply["results"]
    names = []
    scores = []
    for hit in results:
        if hit["kind"] not in (("Repo", "Section") if credit_parent else ("Repo",)):
            continue
        qn = hit.get("parent") if credit_parent and hit.get("parent") else hit.get("qn", "")
        name = qn.removeprefix(prefix)
        if not qn.startswith(prefix) or name not in repos:
            raise ValueError(f"Unknown repository/parent in xray hit: {qn}")
        names.append(name)
        scores.append(hit["score"])
    return fold(names), (scores[0] if scores else 0.0)


async def audit_xray(session: Any, entries: list[dict[str, Any]], prefix: str) -> None:
    stats, _ = await call(session, "get_graph_stats", {"map": MAP})
    expected = documents(entries)
    if stats[MAP]["stats"]["Nodes"] != len(expected):
        raise ValueError("xray node count differs from the frozen corpus")
    for entry in entries:
        for node, name in [(entry, entry["name"])] + [
            (part, f"{entry['name']}.{part['name']}") for part in entry.get("parts", [])
        ]:
            actual, _ = await call(session, "get_graph_node", {"qn": prefix + name})
            if actual["kind"] != node["kind"] or actual["content"] != node["text"]:
                raise ValueError(f"xray content differs from the frozen corpus: {name}")
            if actual.get("attrs", {}) != node.get("attrs", {}):
                raise ValueError(f"xray attributes differ from the frozen corpus: {name}")


async def run_xray(entries: list[dict[str, Any]], questions: dict[str, Any]) -> list[dict[str, Any]]:
    prefix = questions["qn_prefix"]
    repos = {e["name"] for e in entries if e["kind"] == "Repo"}
    rows = []
    async with Client(XRAY_URL, read_timeout_seconds=60) as session:
        await audit_xray(session, entries, prefix)
        for q in questions["questions"]:
            row: dict[str, Any] = {"id": q["id"], "type": q["type"], "language": q["language"], "gold": q["gold"]}
            row["raw"] = {}
            if q["type"] in ("lookup", "graph", "negative"):
                for mode, extra in (("plain", {}), ("kind_repo", {"kind": "Repo"})):
                    args = {"query": q["question"], "map": MAP, "limit": RAW_LIMIT, **extra}
                    reply, took = await measured_call(session, "search_graph", args)
                    row["raw"][mode] = {"args": args, "reply": reply}
                    names, top_score = xray_repos(reply, prefix, repos, credit_parent=True)
                    if q["type"] == "negative":
                        row[mode] = {"top": names[:K], "top_score": top_score, "s": took}
                    elif q["type"] == "graph":
                        row[f"search_{mode}"] = set_score(names[:K], q["gold"]) | {"s": took}
                    else:
                        row[mode] = ranked_score(names, q["gold"]) | {"s": took}
            if q["type"] == "graph":
                args = {"seeds": [prefix + q["seed"]], "depth": 1, "max_nodes": len(documents(entries))}
                reply, took = await measured_call(session, "get_graph_impact", args)
                row["raw"]["graph"] = {"args": args, "reply": reply}
                walked = [
                    n["QN"].removeprefix(prefix)
                    for n in reply["impacted"]
                    if n["Depth"] == 1 and n["QN"].removeprefix(prefix) in repos
                ]
                row["graph"] = set_score(walked, q["gold"]) | {"s": took}
            if q["type"] == "facet":
                args = {"query": q["question"], "map": MAP, "kind": "Repo", **q["args"]}
                reply, took = await measured_call(session, "search_graph", args)
                row["raw"]["facet"] = {"args": args, "reply": reply}
                names, _ = xray_repos(reply, prefix, repos, credit_parent=False)
                scored = set_score(names, q["gold"])
                scored["exact"] = (
                    names == q["gold"] if "order" in q["args"] else not (scored["missed"] or scored["extra"])
                )
                row["facet"] = scored | {"s": took}
            rows.append(row)
    return rows


# --------------------------------------------------------------------- qdrant


def documents(entries: list[dict[str, Any]]) -> list[dict[str, str]]:
    """The 135 node texts xray-memory embeds, each tagged with its repository."""
    docs = []
    for entry in entries:
        repo = entry["name"] if entry["kind"] == "Repo" else ""
        docs.append({"text": entry["text"], "name": entry["name"], "kind": entry["kind"], "repo": repo})
        for part in entry.get("parts", []):
            docs.append({"text": part["text"], "name": part["name"], "kind": part["kind"], "repo": entry["name"]})
    return docs


def audit_qdrant(entries: list[dict[str, Any]]) -> dict[str, Any]:
    response = requests.get(f"{QDRANT_URL}/collections/{COLLECTION}", timeout=30)
    response.raise_for_status()
    info = response.json()["result"]
    payloads = []
    offset = None
    while True:
        body = {"limit": 256, "with_payload": True, "with_vector": False}
        if offset is not None:
            body["offset"] = offset
        response = requests.post(f"{QDRANT_URL}/collections/{COLLECTION}/points/scroll", json=body, timeout=30)
        response.raise_for_status()
        result = response.json()["result"]
        payloads.extend(p["payload"] for p in result["points"])
        offset = result.get("next_page_offset")
        if offset is None:
            break
    expected = Counter((d["kind"], d["name"], d["repo"], d["text"]) for d in documents(entries))
    actual = Counter((p["kind"], p["name"], p["repo"], p["document"]) for p in payloads)
    if actual != expected:
        raise ValueError("Qdrant differs from frozen corpus: missing, extra, duplicated or changed documents")
    return {"documents": len(payloads), "vectors": info["config"]["params"]["vectors"]}


def qdrant_repos(reply: Any, repos: set[str]) -> tuple[list[str], float]:
    if not isinstance(reply, list):
        raise ValueError("vector_find response is not a list")
    names, scores = [], []
    for hit in reply:
        payload = hit["payload"]
        if payload["kind"] not in ("Repo", "Section"):
            continue
        if payload["repo"] not in repos:
            raise ValueError(f"Unknown repository in Qdrant hit: {payload['repo']}")
        names.append(payload["repo"])
        scores.append(hit["score"])
    return fold(names), (scores[0] if scores else 0.0)


async def run_qdrant(entries: list[dict[str, Any]], questions: dict[str, Any], args: argparse.Namespace) -> Any:
    if args.reset:
        # 404 is fine: the collection dies with the cluster on a Codespace restart.
        response = requests.delete(f"{QDRANT_URL}/collections/{COLLECTION}", timeout=30)
        if response.status_code != 404:
            response.raise_for_status()
    rows = []
    async with Client(QDRANT_MCP_URL, read_timeout_seconds=300) as session:
        if args.ingest:
            docs = documents(entries)
            for doc in docs:
                metadata = {key: doc[key] for key in ("name", "kind", "repo")}
                await call(session, "vector_store", {"information": doc["text"], "metadata": metadata})
            print(f"stored {len(docs)} documents in {COLLECTION}")
        audit_qdrant(entries)
        repos = {e["name"] for e in entries if e["kind"] == "Repo"}
        for q in questions["questions"]:
            row: dict[str, Any] = {"id": q["id"], "type": q["type"], "language": q["language"], "gold": q["gold"]}
            if q["type"] == "facet":
                continue
            # No kind filter exists, so over-fetch and keep what belongs to a repository.
            query_args = {"query": q["question"], "limit": RAW_LIMIT}
            reply, took = await measured_call(session, "vector_find", query_args)
            row["raw"] = {"plain": {"args": query_args, "reply": reply}}
            names, top_score = qdrant_repos(reply, repos)
            if q["type"] == "negative":
                row["plain"] = {"top": names[:K], "top_score": top_score, "s": took}
            elif q["type"] == "graph":
                row["search_plain"] = set_score(names[:K], q["gold"]) | {"s": took}
            else:
                row["plain"] = ranked_score(names, q["gold"]) | {"s": took}
            rows.append(row)
    return rows


# -------------------------------------------------------------------- summary


def mean(values: list[float]) -> float:
    return round(statistics.fmean(values), 3) if values else 0.0


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    lookups = [r for r in rows if r["type"] == "lookup"]
    for mode in ("plain", "kind_repo"):
        scored = [r[mode] for r in lookups if mode in r]
        if not scored:
            continue
        uk = [r[mode] for r in lookups if mode in r and r["language"] == "uk"]
        out[f"lookup_{mode}"] = {
            "n": len(scored),
            "hit@1": mean([float(s["hit1"]) for s in scored]),
            f"recall@{K}": mean([s["recall"] for s in scored]),
            f"mrr@{K}": mean([s["rr"] for s in scored]),
            "uk_n": len(uk),
            f"uk_recall@{K}": mean([s["recall"] for s in uk]),
            "p50_ms": round(statistics.median(s["s"] for s in scored) * 1000),
        }
    graphs = [r for r in rows if r["type"] == "graph"]
    for mode in ("graph", "search_plain", "search_kind_repo"):
        scored = [r[mode] for r in graphs if mode in r]
        if scored:
            out[f"graph_{mode}"] = {
                "n": len(scored),
                "precision" if mode == "graph" else f"precision@{K}": mean([s["precision"] for s in scored]),
                "recall" if mode == "graph" else f"recall@{K}": mean([s["recall"] for s in scored]),
                "p50_ms": round(statistics.median(s["s"] for s in scored) * 1000),
            }
    facets = [r["facet"] for r in rows if "facet" in r]
    if facets:
        out["facet"] = {"n": len(facets), "exact": mean([float(f["exact"]) for f in facets])}
    negatives = [r for r in rows if r["type"] == "negative"]
    if negatives:
        mode = "kind_repo" if "kind_repo" in negatives[0] else "plain"
        out["negative_top_scores"] = {r["id"]: round(r[mode]["top_score"], 3) for r in negatives}
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("backend", choices=["xray", "qdrant"])
    parser.add_argument("--ingest", action="store_true", help="qdrant: store the corpus first")
    parser.add_argument("--reset", action="store_true", help=f"qdrant: drop collection {COLLECTION} first")
    args = parser.parse_args()
    if args.reset and not args.ingest:
        parser.error("--reset requires --ingest")
    if args.backend == "xray" and (args.reset or args.ingest):
        parser.error("--reset/--ingest apply only to qdrant")

    entries, questions = load()
    rows = asyncio.run(run_xray(entries, questions) if args.backend == "xray" else run_qdrant(entries, questions, args))
    summary = summarise(rows)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"results-{args.backend}.json"
    report = {
        "method_version": 2,
        "created_at": datetime.now(UTC).isoformat(),
        "backend": args.backend,
        "corpus_sha256": questions["corpus_sha256"],
        "questions_sha256": hashlib.sha256((LAB / "data/questions.json").read_bytes()).hexdigest(),
        "eval_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "method": {
            "raw_limit": RAW_LIMIT,
            "k": K,
            "timing": "full MCP call after one identical warm-up; not isolated index latency",
            "plain": "Repo and Section only; credit parent; deduplicate; same rule for both backends",
            "graph_and_facet": "oracle arguments; graph search top-5 is a separate diagnostic",
            "limits": "256d xray vs 768d Qdrant; separate embedding services; not a controlled vector comparison",
            "negative": "scores only; no calibrated abstention evaluation",
        },
        "audit": {"documents": len(documents(entries)), "content_verified": True},
        "summary": summary,
        "rows": rows,
    }
    if args.backend == "qdrant":
        report["audit"] = audit_qdrant(entries) | {"content_verified": True}
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"-> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
