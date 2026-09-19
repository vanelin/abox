# Lab 5: Agent Memory

A GitHub-profile corpus and evaluation of three retrieval agents. See [results and limitations](evaluation-review.md).

## Layout

| Path | Contents |
|---|---|
| `scripts/` | Corpus generation, MCP calls, ingestion and evaluation |
| `tests/` | Offline unit tests (`test_*.py`) |
| `data/` | Custom topics, frozen corpus, map summary and questions with gold answers |
| `evaluation/` | Campaign manifest, report hashes and answer judgements |
| `.local/lab05/` (repository root) | Generated files and raw reports; ignored by Git |

Deployment manifests live in [`releases/`](../../../releases/). The [maps workflow](../../../.github/workflows/xray-memory-maps-image.yaml) builds from `data/*.catalog.json` and `data/*.summary.txt`.

## Offline checks

Run from the repository root:

```bash
uv run python -m unittest discover -s docs/labs/05/tests -p 'test_*.py' -v
uv run ruff check docs/labs/05
uv run pyright docs/labs/05
uv run docs/labs/05/scripts/summarise.py --review
```

Summarisation requires the raw reports pinned by `evaluation/evaluation-campaign.json`. Unit tests require neither reports nor a cluster.

## Port-forwards and UIs

Nothing is exposed outside the cluster. A forward dies with its pod; re-run it after a release or a restart.

```bash
kubectl -n xray-memory port-forward svc/xray-memory 8085:8085 &          # xray-memory: /ui, /mcp, /search, /status
kubectl -n kagent port-forward svc/kagent-ui 8080:8080 &                 # kagent UI: talk to the agents
kubectl -n kagent port-forward svc/kagent-controller 8083:8083 &         # A2A, used by agentic.py
kubectl -n kagent port-forward svc/qdrant-mcp 3002:3000 &                # Go qdrant-mcp (nomic), used by eval.py qdrant
kubectl -n kagent port-forward svc/qdrant-mcp-official 3001:3000 &       # official qdrant MCP, used by ingest_official.py
kubectl -n qdrant port-forward svc/qdrant 6333:6333 &                    # Qdrant REST and /dashboard
kubectl -n phoenix port-forward svc/phoenix-svc 6006:6006 &              # Phoenix: a trace of every agent run
```

| UI | Local | GitHub Codespaces |
|---|---|---|
| xray-memory graph | <http://localhost:8085/ui?project=vanelin> | `https://$CODESPACE_NAME-8085.app.github.dev/ui?project=vanelin` |
| kagent | <http://localhost:8080> | `https://$CODESPACE_NAME-8080.app.github.dev` |
| Phoenix | <http://localhost:6006> | `https://$CODESPACE_NAME-6006.app.github.dev` |
| Qdrant dashboard | <http://localhost:6333/dashboard#/collections> | `https://$CODESPACE_NAME-6333.app.github.dev/dashboard#/collections` |

Phoenix login: `admin@localhost` / `admin` (chart default).

Keep Codespaces ports private: 8085 is also the unauthenticated `/mcp`.

Qdrant holds `abox-nomic` and `abox-minilm`, 135 points each; re-ingest after a Codespace restart.

Open the graph with `?project=vanelin`: without it the server shows the empty `session` notes map. The page highlights the nodes each search hits:

```bash
uv run docs/labs/05/scripts/xray.py search_graph query="gitops with flux and terraform" kind=Repo
```

## Usage

```bash
# Read GitHub via gh; write the generated corpus to .local/lab05/.
uv run docs/labs/05/scripts/catalog.py vanelin --topics docs/labs/05/data/topics.json

# Requires the port-forwards above.
uv run docs/labs/05/scripts/xray.py search_graph query=Terraform kind=Repo
uv run docs/labs/05/scripts/ingest_official.py
uv run docs/labs/05/scripts/eval.py xray
uv run docs/labs/05/scripts/eval.py qdrant

# Calls the LLM and consumes tokens.
uv run docs/labs/05/scripts/agentic.py ask xray --ids l02,g01,n02
```

Official ingestion needs MCP on port 3001 and Qdrant on 6333; run one writer. Generating a corpus does not replace the frozen dataset. New experiments must align corpus versions, gold answers, hashes and stored documents.
