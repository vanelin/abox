#!/usr/bin/env python3
"""Lab 5: build the corpus for an xray-memory map from a GitHub profile.

xray-memory's `servicemap` reads a catalog -- {"entries": [...]} -- and turns
every entry into a graph node:

  kind, name   the node's kind and the tail of its qualified name
  text         the node's content. It is ALL that gets embedded and searched,
               so the name and kind are spelled out in it here
  attrs        string key/values, filterable (attr=year=2023) and sortable
  links        [{rel, to}] -- typed edges to other entries, by name. Only
               calls, imports, inherits, implements and references are walked
               by get_graph_impact; any other rel is visible on the node but
               never traversed, so "what depends on Terraform" needs one of
               the five. The target's kind says what the reference means.
  parts        child entries, joined to the parent by a `contains` edge

Entries and where they come from:

  Repo      the user's public repositories; text = GitHub's description plus
            the README's first prose paragraph
    Section   parts of a Repo: the README's sections
  Language  every language GitHub detects in a repository   <- references
  Tool      file-tree evidence, see TOOLS                    <- references
  Upstream  the parent of a fork                             <- inherits
  Topic     topics.json, written by hand -- the one part an
            API cannot give                                  <- references

  uv run docs/labs/05/catalog.py vanelin
  uv run docs/labs/05/catalog.py vanelin --topics docs/labs/05/topics.json

Writes .local/lab05/<user>.json and lists the repositories whose description
is still empty; fill those in topics.json under "descriptions".
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / ".local" / "lab05"
MAX_SECTIONS = 6
SECTION_CHARS = 800

# A tool is present when any path in the repository's tree matches.
TOOLS: dict[str, str] = {
    "Docker": r"(^|/)Dockerfile[^/]*$|(^|/)docker-compose[^/]*\.ya?ml$",
    "Helm": r"(^|/)Chart\.yaml$",
    "Terraform": r"\.tf$",
    "GitHub Actions": r"^\.github/workflows/[^/]+\.ya?ml$",
    "Jenkins": r"(^|/)Jenkinsfile[^/]*$|\.groovy$",
    "Make": r"(^|/)Makefile$",
    "Kustomize": r"(^|/)kustomization\.ya?ml$",
    "Go modules": r"(^|/)go\.mod$",
    "Python packaging": r"(^|/)(requirements[^/]*\.txt|pyproject\.toml)$",
    "Ansible": r"(^|/)(playbook[^/]*\.ya?ml|ansible\.cfg)$",
    "Devcontainer": r"^\.devcontainer/",
}
# Flux and Argo CD are recognised by what their manifests say, not by a path.
CONTENT_TOOLS: dict[str, str] = {
    "Flux": r"toolkit\.fluxcd\.io|fluxcd\.controlplane\.io",
    "Argo CD": r"argoproj\.io",
}


def gh(path: str) -> Any:
    """GET a GitHub API path with the gh CLI; None on 404 (empty repo, no README)."""
    done = subprocess.run(["gh", "api", path], capture_output=True, text=True)
    if done.returncode != 0:
        if "404" in done.stderr or "409" in done.stderr:
            return None
        sys.exit(f"gh api {path}: {done.stderr.strip()}")
    return json.loads(done.stdout)


def prose(block: str) -> str:
    """One markdown block as plain text: no images, badges, link targets or HTML."""
    # Table rows are layout, not prose: they embed as noise.
    text = " ".join(line.strip() for line in block.splitlines() if not line.lstrip().startswith("|"))
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)  # images and badges, before the links that wrap them
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    # The map ships in a public image; a README's contact addresses are not corpus.
    return re.sub(r"[\w.+-]+@[\w-]+(\.[\w-]+)+", "", text).strip()


def first_paragraph(markdown: str) -> str:
    """The first paragraph of prose: no headings, lists, tables or code."""
    markdown = re.sub(r"```.*?```", "", markdown, flags=re.S)
    for block in re.split(r"\n\s*\n", markdown):
        text = prose(block)
        if len(text) > 40 and not re.match(r"[#|\-*>]|\d+\.", text):
            return text[:400]
    return ""


def sections(markdown: str, repo: str) -> list[dict[str, str]]:
    """The README's `##` sections as parts, code blocks dropped, names unique."""
    markdown = re.sub(r"```.*?```", "", markdown, flags=re.S)
    parts: list[dict[str, str]] = []
    for chunk in re.split(r"^##\s+", markdown, flags=re.M)[1:]:
        heading, _, body = chunk.partition("\n")
        heading = prose(heading).strip("# ")
        text = " ".join(prose(block) for block in re.split(r"\n\s*\n", body)).strip()
        if heading and len(text) > 60 and heading not in {p["name"] for p in parts}:
            parts.append(
                {"kind": "Section", "name": heading, "text": f"{repo} README, {heading}: {text[:SECTION_CHARS]}"}
            )
    return parts[:MAX_SECTIONS]


def tools_of(full_name: str, branch: str) -> list[str]:
    tree = gh(f"repos/{full_name}/git/trees/{branch}?recursive=1")
    if not tree:
        return []
    paths = [entry["path"] for entry in tree["tree"] if entry["type"] == "blob"]
    found = [tool for tool, pattern in TOOLS.items() if any(re.search(pattern, p) for p in paths)]
    # Only a handful of YAML files is worth opening to tell Flux from Argo CD.
    for path in [p for p in paths if re.search(r"\.ya?ml$", p)][:40]:
        if all(tool in found for tool in CONTENT_TOOLS):
            break
        blob = gh(f"repos/{full_name}/contents/{path}?ref={branch}")
        if not blob or blob.get("encoding") != "base64":
            continue
        text = base64.b64decode(blob["content"]).decode("utf-8", "replace")
        found += [t for t, pattern in CONTENT_TOOLS.items() if t not in found and re.search(pattern, text)]
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("user")
    parser.add_argument("--topics", type=Path, help="hand-written topics and missing descriptions")
    args = parser.parse_args()

    manual = json.loads(args.topics.read_text()) if args.topics else {}
    descriptions: dict[str, str] = manual.get("descriptions", {})

    entries: dict[str, dict[str, Any]] = {}

    def entry(name: str, kind: str, text: str) -> dict[str, Any]:
        return entries.setdefault(name, {"kind": kind, "name": name, "text": text, "links": []})

    bare: list[str] = []
    for listed in gh(f"users/{args.user}/repos?per_page=100&type=owner") or []:
        repo = gh(f"repos/{listed['full_name']}")  # the list omits `parent`
        name = repo["name"]
        print(f"{name} ...", file=sys.stderr)

        readme = gh(f"repos/{repo['full_name']}/readme")
        markdown = base64.b64decode(readme["content"]).decode("utf-8", "replace") if readme else ""
        summary, paragraph = (repo["description"] or "").rstrip("."), first_paragraph(markdown)
        if paragraph.startswith(summary):  # a README that opens with the description says it once
            summary = ""
        about = descriptions.get(name) or " ".join(p.rstrip(".") + "." for p in (summary, paragraph) if p)
        if not about:
            bare.append(name)

        languages = list(gh(f"repos/{repo['full_name']}/languages") or {})
        tools = tools_of(repo["full_name"], repo["default_branch"])
        parent = repo["parent"]["full_name"] if repo.get("parent") else ""

        item = entry(name, "Repo", "")
        item["text"] = (
            f"Repository {name}. {about} "
            + (f"Fork of {parent}. " if parent else f"Non-fork repository owned by {args.user}. ")
            + (f"Languages: {', '.join(languages)}. " if languages else "")
            + (f"Tools: {', '.join(tools)}. " if tools else "")
            + f"Created {repo['created_at'][:4]}, last pushed {repo['pushed_at'][:4]}, "
            + f"{repo['stargazers_count']} stars."
        )
        item["attrs"] = {
            "year": repo["pushed_at"][:4],
            "created": repo["created_at"][:4],
            "fork": str(repo["fork"]).lower(),
            "language": repo["language"] or "none",
            "stars": str(repo["stargazers_count"]),
        }
        item["parts"] = sections(markdown, name)

        for language in languages:
            entry(language, "Language", f"Programming language {language}.")
            item["links"].append({"rel": "references", "to": language})
        for tool in tools:
            entry(tool, "Tool", f"DevOps tool {tool}, detected from the repository's files.")
            item["links"].append({"rel": "references", "to": tool})
        if parent:
            entry(parent, "Upstream", f"Upstream repository {parent}, the original that {name} was forked from.")
            item["links"].append({"rel": "inherits", "to": parent})

    repo_names = {name for name, item in entries.items() if item["kind"] == "Repo"}
    unknown = descriptions.keys() - repo_names
    if unknown:
        sys.exit(f"topics.json: descriptions name unknown repositories: {', '.join(sorted(unknown))}")

    for topic, body in manual.get("topics", {}).items():
        entry(topic, "Topic", f"Topic {topic}. {body['description']}")
        for name in body["repos"]:
            if name not in repo_names:
                sys.exit(f"topics.json: topic {topic!r} names unknown repository {name!r}")
            entries[name]["links"].append({"rel": "references", "to": topic})

    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"{args.user}.json"
    out.write_text(json.dumps({"entries": list(entries.values())}, indent=2, ensure_ascii=False) + "\n")

    kinds: dict[str, int] = {}
    for item in entries.values():
        kinds[item["kind"]] = kinds.get(item["kind"], 0) + 1
        kinds["Section"] = kinds.get("Section", 0) + len(item.get("parts", []))
    print(f"{out.relative_to(ROOT)}: {sum(kinds.values())} nodes {kinds}")
    if bare:
        print("no description, add to topics.json:", ", ".join(bare))


if __name__ == "__main__":
    main()
