#!/usr/bin/env python3
"""Evaluate one embedding model on the abox corpus (ADR-0001 test, step 4).

Usage: uv run docs/labs/03/eval.py nomic|gemma|qwen [--qdrant http://127.0.0.1:6333]

Starts llama-server for the model, embeds chunks.jsonl and questions.json,
scores hit@1/hit@3 at full, 256 and 128 dimensions in memory, and optionally
repeats the search through Qdrant as a cross-check. Writes results-<model>-<run_id>.json.
Checks model SHA256 against the pinned MODEL_SPECS entries in Makefile before startup.

All models use a 2048-token test context; longer Nomic contexts are untested here,
not proven impossible by GGUF metadata.
The server returns raw vectors (--embd-normalize -1). Nomic uses LayerNorm then
truncation then L2, including at full dimension; Gemma and Qwen use truncation then L2.
The lexical baseline does not translate Ukrainian; shared identifiers can still match
English chunks, so a zero score is possible but not guaranteed.
Equal in-memory scores use descending chunk ID as a tie-break; Qdrant may order ties
differently. An empty over_ctx records that the context check passed.
External mode: --endpoint http://127.0.0.1:8082 [--ctx-size 2048]. Requires /health, /tokenize and raw /v1/embeddings.
Remote model hash, runtime version and RSS are not inferred from local files; verify and measure them separately.
stdlib + requests only.
"""

import argparse
import hashlib
import json
import math
import re
import socket
import statistics
import subprocess
import sys
import time
import uuid
from pathlib import Path

import requests

HERE = Path(__file__).parent
ROOT = HERE.parent.parent.parent
DATA = ROOT / ".local/lab03"  # generated inputs and outputs; gitignored
SERVER = ROOT / ".local/llama.cpp/build/bin/llama-server"
PORT = 8081
BASE_URL = f"http://127.0.0.1:{PORT}"
DIMS = [256, 128]
BATCH = 8
FULL_DIMS = {"nomic": 768, "gemma": 768, "qwen": 1024}

MODELS = {
    # file, pooling, doc prefix, query prefix, layernorm-before-truncate
    "nomic": ("nomic-embed-text-v1.5.Q8_0.gguf", "mean", "search_document: ", "search_query: ", True),
    "gemma": ("embeddinggemma-300M-Q8_0.gguf", "mean", "title: none | text: ", "task: search result | query: ", False),
    "qwen": (
        "Qwen3-Embedding-0.6B-Q8_0.gguf",
        "last",
        "",
        "Instruct: Given a question about a Kubernetes/OpenTofu repository, "
        "retrieve the file section that answers it\nQuery: ",
        False,
    ),
}


# ---------- vector maths (pure python) ----------
def l2(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def layernorm(v, eps=1e-5):
    m = sum(v) / len(v)
    var = sum((x - m) ** 2 for x in v) / len(v)
    s = math.sqrt(var + eps)
    return [(x - m) / s for x in v]


def prep(v, dim, ln):
    if ln:
        v = layernorm(v)
    return l2(v[:dim] if dim else v)


def dot(a, b):
    return sum(x * y for x, y in zip(a, b, strict=True))


# ---------- server ----------
def checked_model_sha(model_file):
    pins = dict(
        re.findall(
            r"^[ \t]+(\S+\.gguf)\|[^|\s]+\|[0-9a-f]{40}\|([0-9a-f]{64})[ \t]*\\?$",
            (ROOT / "Makefile").read_text(),
            re.MULTILINE,
        )
    )
    if model_file not in pins:
        sys.exit(f"No SHA256 pin found in Makefile for {model_file}")
    with (ROOT / ".local/models" / model_file).open("rb") as fh:
        actual = hashlib.file_digest(fh, "sha256").hexdigest()
    if actual != pins[model_file]:
        sys.exit(
            f"Model SHA256 mismatch for {model_file}: expected {pins[model_file]}, got {actual}; "
            "check the file and Makefile pin before running"
        )
    return actual


def start(model_file, pooling):
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", PORT)) == 0:
            sys.exit(f"Port {PORT} is already in use; stop that server first")
    p = subprocess.Popen(
        [
            str(SERVER),
            "-m",
            str(ROOT / ".local/models" / model_file),
            "--embedding",
            "--pooling",
            pooling,
            "--embd-normalize",
            "-1",
            "--host",
            "127.0.0.1",
            "--port",
            str(PORT),
            "--ctx-size",
            "2048",
            "--parallel",
            "1",
            "--threads",
            "2",
            "--threads-batch",
            "2",
            "-ub",
            "2048",
            "-b",
            "2048",
        ],
        stdout=open(DATA / f"server-{model_file}.log", "w"),
        stderr=subprocess.STDOUT,
    )
    for _ in range(120):
        try:
            if requests.get(f"http://127.0.0.1:{PORT}/health", timeout=2).ok:
                return p
        except requests.RequestException:
            pass
        if p.poll() is not None:
            sys.exit(f"llama-server exited early; see {DATA}/server-{model_file}.log")
        time.sleep(1)
    p.terminate()
    p.wait()
    sys.exit("llama-server did not become healthy")


def embed(texts, expected_dim):
    r = requests.post(f"{BASE_URL}/v1/embeddings", json={"input": texts}, timeout=600)
    r.raise_for_status()
    data = sorted(r.json()["data"], key=lambda d: d["index"])
    if [d["index"] for d in data] != list(range(len(texts))):
        raise ValueError("Embedding response count or indices do not match inputs")
    vectors = [d["embedding"] for d in data]
    for v in vectors:
        if len(v) != expected_dim or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in v):
            raise ValueError(f"Expected {expected_dim} finite numeric coordinates per embedding")
        if not any(v):
            raise ValueError("Received a zero embedding")
    return vectors


def ntokens(text):
    r = requests.post(
        f"{BASE_URL}/tokenize",
        json={"content": text, "add_special": True, "parse_special": True},
        timeout=60,
    )
    r.raise_for_status()
    return len(r.json()["tokens"])


def rss_mb(pid):
    return int(open(f"/proc/{pid}/status").read().split("VmRSS:")[1].split()[0]) // 1024


# ---------- lexical baseline ----------
def lexical_rank(question, chunks):
    terms = {
        t for t in "".join(c if c.isalnum() or c in "_-./" else " " for c in question.lower()).split() if len(t) > 2
    }
    scored = []
    for c in chunks:
        low = c["text"].lower()
        scored.append((sum(1 for t in terms if t in low), c["id"]))
    scored.sort(key=lambda x: -x[0])
    return [i for s, i in scored if s > 0][:3]


# ---------- main ----------
def main():
    global BASE_URL
    parser = argparse.ArgumentParser(description="Evaluate local or external llama-server embeddings.")
    parser.add_argument("model", choices=MODELS)
    parser.add_argument("--qdrant", help="Optional Qdrant base URL")
    parser.add_argument("--endpoint", help="Existing llama-server base URL; does not start or stop a server")
    parser.add_argument("--ctx-size", type=int, default=2048, help="External server input limit (default: 2048)")
    args = parser.parse_args()
    if args.ctx_size <= 0 or (not args.endpoint and args.ctx_size != 2048):
        parser.error("Use a positive --ctx-size; local runs require 2048 to preserve the baseline")
    if args.endpoint and not args.endpoint.startswith(("http://", "https://")):
        parser.error("--endpoint must be an HTTP(S) base URL")
    BASE_URL = args.endpoint.rstrip("/") if args.endpoint else f"http://127.0.0.1:{PORT}"
    name, qdrant = args.model, args.qdrant
    model_file, pooling, dpre, qpre, ln = MODELS[name]
    DATA.mkdir(parents=True, exist_ok=True)

    corpus_bytes = (HERE / "chunks.jsonl").read_bytes()  # frozen corpus, see questions.json
    question_bytes = (HERE / "questions.json").read_bytes()
    corpus_sha = hashlib.sha256(corpus_bytes).hexdigest()
    chunks = [json.loads(line) for line in corpus_bytes.splitlines()]
    question_data = json.loads(question_bytes)
    qs = question_data["questions"]
    if corpus_sha != question_data["corpus_sha256"]:
        sys.exit("Corpus changed: review chunks and question labels before running")
    chunk_ids = {c["id"] for c in chunks}
    if any(i not in chunk_ids for q in qs for i in q["relevant_ids"]):
        sys.exit("Question labels reference missing chunks")
    full_dim = FULL_DIMS[name]
    run_id = uuid.uuid4().hex[:12]
    srv = None
    if args.endpoint:
        requests.get(f"{BASE_URL}/health", timeout=10).raise_for_status()
        model_sha, runtime = None, None
        print("External server: verify model SHA256, runtime and raw-vector settings at deployment.", flush=True)
    else:
        model_sha = checked_model_sha(model_file)
        print(f"Model SHA256 matches Makefile: {model_file}", flush=True)
        runtime = subprocess.check_output([str(SERVER), "--version"], stderr=subprocess.STDOUT, text=True).strip()
        srv = start(model_file, pooling)
    try:
        # token check: enforce the declared context, including prefixes and special tokens
        toks = [ntokens(dpre + c["text"]) for c in chunks]
        over = [(c["id"], t) for c, t in zip(chunks, toks, strict=True) if t > args.ctx_size]
        qtoks = [ntokens(qpre + q["question"]) for q in qs]
        over += [(q["id"], t) for q, t in zip(qs, qtoks, strict=True) if t > args.ctx_size]
        if over:
            sys.exit(f"Inputs exceed {args.ctx_size} tokens (including prompts/special tokens): {over}")
        print(f"Token check passed: chunks max={max(toks)}, questions max={max(qtoks)}", flush=True)
        # embedding generation
        t0 = time.time()
        raw = []
        for i in range(0, len(chunks), BATCH):
            raw += embed([dpre + c["text"] for c in chunks[i : i + BATCH]], full_dim)
        t_index = time.time() - t0
        rss = rss_mb(srv.pid) if srv else None
        vecs = {d: [prep(v, d, ln) for v in raw] for d in [full_dim] + DIMS}
        # query latency: warm, 10 repeats of one question
        embed([qpre + qs[0]["question"]], full_dim)
        lat = []
        for _ in range(10):
            t = time.time()
            embed([qpre + qs[0]["question"]], full_dim)
            lat.append((time.time() - t) * 1000)
        p50 = statistics.median(lat)
        # query latency: ten distinct questions, one at a time, warm server
        dlat = []
        for q in qs:
            t = time.time()
            embed([qpre + q["question"]], full_dim)
            dlat.append((time.time() - t) * 1000)
        dlat_sorted = sorted(dlat)
        distinct_p50 = statistics.median(dlat)
        distinct_p95 = dlat_sorted[max(0, math.ceil(0.95 * len(dlat_sorted)) - 1)]
        # search
        qraw = embed([qpre + q["question"] for q in qs], full_dim)
        results = {}
        for d in [full_dim] + DIMS:
            per_q = []
            for q, qv in zip(qs, qraw, strict=True):
                qp = prep(qv, d, ln)
                ranked = sorted(((dot(qp, cv), c["id"]) for cv, c in zip(vecs[d], chunks, strict=True)), reverse=True)
                top = [i for _, i in ranked[:3]]
                rel = set(q["relevant_ids"])
                per_q.append(
                    {
                        "q": q["id"],
                        "lang": q["language"],
                        "top3": top,
                        "hit1": top[0] in rel,
                        "hit3": bool(rel & set(top)),
                    }
                )
            results[d] = per_q
        # Fresh collections for this run; never delete existing data.
        qd = None
        if qdrant:
            qd = {}
            for d in [full_dim] + DIMS:
                coll = f"lab03_{name}_{d}_{run_id}"
                url = f"{qdrant.rstrip('/')}/collections/{coll}"
                requests.put(url, json={"vectors": {"size": d, "distance": "Cosine"}}, timeout=60).raise_for_status()
                pts = [
                    {"id": i, "vector": v, "payload": {"cid": c["id"]}}
                    for i, (v, c) in enumerate(zip(vecs[d], chunks, strict=True))
                ]
                t0 = time.perf_counter()
                requests.put(
                    f"{url}/points", params={"wait": "true"}, json={"points": pts}, timeout=60
                ).raise_for_status()
                upsert_seconds = time.perf_counter() - t0
                comparisons = []
                for q, qv, mem in zip(qs, qraw, results[d], strict=True):
                    r = requests.post(
                        f"{url}/points/search",
                        json={"vector": prep(qv, d, ln), "limit": 3, "with_payload": True, "params": {"exact": True}},
                        timeout=60,
                    )
                    r.raise_for_status()
                    top = [h["payload"]["cid"] for h in r.json()["result"]]
                    comparisons.append({"q": q["id"], "top3": top, "agrees": top == mem["top3"]})
                agree = sum(c["agrees"] for c in comparisons)
                qd[str(d)] = {
                    "collection": coll,
                    "top3_agree": f"{agree}/{len(qs)}",
                    "upsert_seconds": round(upsert_seconds, 3),
                    "details": comparisons,
                }
    finally:
        if srv is not None:
            srv.terminate()
            srv.wait()

    baseline = []
    for q in qs:
        top = lexical_rank(q["question"], chunks)
        rel = set(q["relevant_ids"])
        baseline.append(
            {
                "q": q["id"],
                "lang": q["language"],
                "top3": top,
                "hit1": bool(top) and top[0] in rel,
                "hit3": bool(rel & set(top)),
            }
        )

    def summary(rows):
        def cnt(rs, k):
            return f"{sum(r[k] for r in rs)}/{len(rs)}"

        by = {"all": rows, "en": [r for r in rows if r["lang"] == "en"], "uk": [r for r in rows if r["lang"] == "uk"]}
        return {g: {"hit1": cnt(rs, "hit1"), "hit3": cnt(rs, "hit3")} for g, rs in by.items()}

    out = {
        "model": name,
        "file": model_file,
        "pooling": pooling,
        "layernorm_before_truncate": ln,
        "run_id": run_id,
        "corpus_sha256": corpus_sha,
        "questions_sha256": hashlib.sha256(question_bytes).hexdigest(),
        "model_sha256": model_sha,
        "model_pin_source": None if args.endpoint else "Makefile MODEL_SPECS",
        "endpoint": BASE_URL,
        "execution_mode": "external" if args.endpoint else "local",
        "runtime_version": runtime,
        "postprocessing": "LayerNorm -> truncate -> L2 (including full)" if ln else "truncate -> L2 (including full)",
        "settings": {"ctx_size": args.ctx_size, "batch": BATCH}
        if args.endpoint
        else {"threads": 2, "threads_batch": 2, "parallel": 1, "ctx_size": 2048, "batch": BATCH},
        "full_dim": full_dim,
        "max_tokens": max(toks),
        "total_tokens": sum(toks),
        "mean_tokens": round(sum(toks) / len(toks), 1),
        "max_query_tokens": max(qtoks),
        "over_ctx": over,
        "embedding_seconds": round(t_index, 1),
        "rss_mb": rss,
        "query_p50_ms": round(p50, 1),
        "distinct_query_p50_ms": round(distinct_p50, 1),
        "distinct_query_p95_ms": round(distinct_p95, 1),
        "summary": {str(d): summary(results[d]) for d in results},
        "lexical_baseline": summary(baseline),
        "details": {str(d): results[d] for d in results},
        "baseline_details": baseline,
        "qdrant": qd,
    }
    result_path = DATA / f"results-{name}-{run_id}.json"
    with result_path.open("x") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)
    print(f"Results saved: {result_path}")

    print(
        f"\n{name}: dim={full_dim} tokens_max={max(toks)} over_ctx={len(over)} "
        f"embedding={t_index:.1f}s rss={str(rss) + 'MB' if rss is not None else 'unmeasured'} "
        f"repeat_p50={p50:.0f}ms distinct_p50/p95={distinct_p50:.0f}/{distinct_p95:.0f}ms"
    )
    print(f"{'dim':>5} {'all h@1':>8} {'all h@3':>8} {'en h@1':>7} {'en h@3':>7} {'uk h@1':>7} {'uk h@3':>7}")
    for d in results:
        s = out["summary"][str(d)]
        print(
            f"{d:>5} {s['all']['hit1']:>8} {s['all']['hit3']:>8} "
            f"{s['en']['hit1']:>7} {s['en']['hit3']:>7} {s['uk']['hit1']:>7} {s['uk']['hit3']:>7}"
        )
    b = out["lexical_baseline"]
    print(
        f"{'lex':>5} {b['all']['hit1']:>8} {b['all']['hit3']:>8} "
        f"{b['en']['hit1']:>7} {b['en']['hit3']:>7} {b['uk']['hit1']:>7} {b['uk']['hit3']:>7}"
    )
    if qd:
        for d, check in qd.items():
            print(f"qdrant {d}: top3 agree={check['top3_agree']} collection={check['collection']}")
    misses = [r for r in results[full_dim] if not r["hit3"]]
    if misses:
        print("misses at full dim:")
        for r in misses:
            print(f"  {r['q']} ({r['lang']}): got {r['top3']}")


if __name__ == "__main__":
    main()
