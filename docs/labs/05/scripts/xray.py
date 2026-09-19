#!/usr/bin/env python3
"""Lab 5: call one xray-memory MCP tool by hand and print what an agent would see.

The HTTP /search endpoint is a shortcut; facets, graph walks and the notes
live behind MCP, which needs a session handshake curl does not do. This is
that handshake and nothing else -- no prompt, no model, no parsing.

  kubectl -n xray-memory port-forward svc/xray-memory 8085:8085

  uv run docs/labs/05/scripts/xray.py                        # list the tools and their parameters
  uv run docs/labs/05/scripts/xray.py search_graph query="kubernetes controller in go" kind=Repo
  uv run docs/labs/05/scripts/xray.py search_graph query=repositories attr=fork=false order=stars:desc limit=10
  uv run docs/labs/05/scripts/xray.py get_graph_node qn="vanelin//vanelin.catalog.json::kbot"
  uv run docs/labs/05/scripts/xray.py get_graph_impact seeds='["vanelin//vanelin.catalog.json::Terraform"]'
  uv run docs/labs/05/scripts/xray.py remember text="..." attrs="about=kbot,topic=lab5" ttl=never
  uv run docs/labs/05/scripts/xray.py recall query=kbot

A value that parses as JSON (a number, true, a [list]) is sent as that type;
anything else is sent as a string. Only the first `=` splits, so
attr=fork=false reaches the tool as attr "fork=false".
"""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from mcp import Client

URL = "http://127.0.0.1:8085/mcp"


def parse(pairs: list[str]) -> dict[str, Any]:
    args: dict[str, Any] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep:
            raise SystemExit(f"{pair!r}: expected key=value")
        try:
            args[key] = json.loads(value)
        except json.JSONDecodeError:
            args[key] = value
    return args


def show(text: str) -> None:
    try:
        print(json.dumps(json.loads(text), indent=2, ensure_ascii=False))
    except json.JSONDecodeError:
        print(text)


async def run(args: argparse.Namespace) -> None:
    async with Client(args.url, read_timeout_seconds=60) as session:
        if not args.tool:
            for tool in (await session.list_tools()).tools:
                schema = tool.input_schema or {}
                required = set(schema.get("required", []))
                params = ", ".join(f"{name}{'*' if name in required else ''}" for name in schema.get("properties", {}))
                print(f"{tool.name}({params})")
            return
        result = await session.call_tool(args.tool, parse(args.args))
        for block in result.content:
            show(getattr(block, "text", str(block)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("tool", nargs="?", help="omit to list the tools")
    parser.add_argument("args", nargs="*", metavar="key=value")
    parser.add_argument("--url", default=URL)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
