#!/usr/bin/env python3
"""Split the abox corpus into meaningful chunks for the embedding test (ADR-0001).

Output: one JSON object per line with path, kind, start/end line (1-based,
inclusive), a short id and the text. Rules are deliberately simple and
inspectable; the same chunks are fed to every model.
"""

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())
OUT = ROOT / ".local/lab03/chunks.jsonl"  # generated; gitignored
MAX_LINES = 80  # readability heuristic; token limits must be checked per model


def tracked():
    files = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).split()
    keep = re.compile(r"(\.md|\.tf|\.ya?ml|\.sh|Makefile|Dockerfile)$")
    return [f for f in files if keep.search(f)]


def emit(chunks, path, kind, start, lines):
    """Append a chunk; split oversized ones on blank lines."""
    if not "".join(lines).strip():
        return
    if len(lines) <= MAX_LINES:
        chunks.append((path, kind, start, start + len(lines) - 1, "".join(lines)))
        return
    buf, s = [], start
    for i, ln in enumerate(lines):
        buf.append(ln)
        if len(buf) >= MAX_LINES // 2 and not ln.strip():
            chunks.append((path, kind, s, start + i, "".join(buf)))
            buf, s = [], start + i + 1
    if buf:
        chunks.append((path, kind, s, start + len(lines) - 1, "".join(buf)))


def by_regex(lines, pattern, leading_comments=False):
    """Boundaries at lines matching pattern; preamble before first match kept."""
    idx = [i for i, ln in enumerate(lines) if re.match(pattern, ln)]
    if leading_comments:
        for n, i in enumerate(idx):
            while i > 0 and (not lines[i - 1].strip() or lines[i - 1].startswith("#")):
                i -= 1
            idx[n] = i
    bounds = [0] + idx + [len(lines)]
    return [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1) if bounds[i] < bounds[i + 1]]


def split_md(lines):
    # h2/h3 sections; h1 + intro become the first chunk. Code fences are not split.
    return by_regex(lines, r"^#{2,3} ")


def split_tf(lines):
    return by_regex(
        lines, r"^(resource|module|variable|output|provider|terraform|data|locals)\b", leading_comments=True
    )


def split_yaml(lines):
    return by_regex(lines, r"^---\s*$")


def split_sh(lines):
    return by_regex(lines, r"^[A-Za-z_][A-Za-z0-9_]*\(\)\s*\{")


def split_make(lines):
    bounds, in_variables = [0], False
    for i, ln in enumerate(lines):
        assignment = re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*(?:[:?+]?=)", ln)
        target = re.match(r"^[A-Za-z_][A-Za-z0-9_-]*:(?!=)", ln)
        if target or (assignment and not in_variables):
            start = i
            while start > 0 and (not lines[start - 1].strip() or lines[start - 1].startswith("#")):
                start -= 1
            bounds.append(start)
        if target or assignment:
            in_variables = bool(assignment)
    bounds = sorted(set(bounds + [len(lines)]))
    return list(zip(bounds, bounds[1:], strict=False))


def main():
    chunks = []
    for rel in tracked():
        lines = (ROOT / rel).read_text().splitlines(keepends=True)
        if rel.endswith(".md"):
            kind, spans = "md", split_md(lines)
        elif rel.endswith(".tf"):
            kind, spans = "tf", split_tf(lines)
        elif rel.endswith((".yaml", ".yml")):
            kind, spans = "yaml", split_yaml(lines)
        elif rel.endswith(".sh"):
            kind, spans = "sh", split_sh(lines)
        elif rel.endswith("Makefile"):
            kind, spans = "make", split_make(lines)
        else:
            kind, spans = "docker", [(0, len(lines))]
        for a, b in spans:
            emit(chunks, rel, kind, a + 1, lines[a:b])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w") as fh:
        for path, kind, s, e, text in chunks:
            fh.write(
                json.dumps(
                    {"id": f"{path}:{s}-{e}", "path": path, "kind": kind, "start": s, "end": e, "text": text},
                    ensure_ascii=False,
                )
                + "\n"
            )
    # summary
    from collections import Counter

    c = Counter(k for _, k, *_ in chunks)
    sizes = sorted(len(t) for *_, t in chunks)
    print(f"{len(chunks)} chunks -> {OUT.relative_to(ROOT)}")
    print("by kind:", dict(c))
    print(f"chars: min={sizes[0]} p50={sizes[len(sizes) // 2]} p90={sizes[int(len(sizes) * 0.9)]} max={sizes[-1]}")


if __name__ == "__main__":
    main()
