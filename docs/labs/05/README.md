# Lab 5: Agent Memory

A GitHub-profile corpus and evaluation of three retrieval agents. See [results and limitations](evaluation-review.md).

## Layout

| Path | Contents |
|---|---|
| `scripts/` | Corpus generation, MCP calls, ingestion, evaluation and the voice-agent launcher |
| `tests/` | Offline unit tests (`test_*.py`) |
| `patches/` | Local fixes to upstream lab components |
| `voice/` | Helm values for the optional voice agent |
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

## Optional 5: Voice agent

Verified on 2026-09-19: Gemini Live delegated to kagent through A2A and used xray-memory across conversations. Built locally from upstream voice-agent commit `37a515c498dde0ef665fdeb501cc772b68ca3a79`, loaded into Kind as `voice-agent:lab5`, and installed with Helm. The clone stays in the gitignored `.local/lab05/`; this deployment is not managed by Flux.

Two fixes: the [A2A patch](patches/voice-agent-artifacts.patch) reads kagent replies from `Task.artifacts`; Helm values set numeric UID/GID `65532` so `runAsNonRoot` accepts the image. Memory uses port 8085, the Codespace host is allowlisted, and the Gemini Secret is exposed as `GOOGLE_API_KEY`.

| Check | Recorded evidence |
|---|---|
| A2A delegation | `ask_xray` ×2, `ask_k8s` ×7 returned response text |
| Direct memory search | `search_graph` queried the `vanelin` corpus |
| Write, 19:49:14 | `remember`: kbot rewrite plan, `about=kbot`, `ttl=never` |
| Read in a new session, 19:51:07 | `recall`: the same note returned after reconnecting |
| Delete, 19:51:31 | `forget` used the recalled qualified name; response reported 0 notes |

Evidence: `.local/lab05/voice/evidence-2026-09-19.log` (ignored by Git; some response text is truncated). These calls demonstrate integration, not accuracy of every answer. Automatic goodbye was not verified: no `end_conversation` call or closing summary note was recorded. TTL expiry and recovery after pod restart were not tested.

### Ukrainian session, 19:55–19:58

- **English search queries:** the user reported speaking Ukrainian; tool logs show English queries such as `Go projects` and `Terraform projects`. This demonstrates query reformulation, but does not establish its effect on retrieval accuracy.
- **Language preference:** at 19:56:11, `remember` saved “User prefers to communicate in Ukrainian” with the title “Language Preference”. No TTL was supplied; the server returned expiry `2026-09-26T19:56:11Z` and one stored note. The earlier zero-note state was therefore temporary; expiry itself remains untested.
- **Tool selection:** at 19:56:57, the agent used `kind=Repo`, `order=stars:desc`, `limit=5` for star ranking. Later Go and Terraform queries used plain search without a kind filter or graph traversal, so complete membership was not established.

Voice and retrieval agents share the same xray-memory session map. The preference can be retrieved across agents; this setup does not isolate notes per user. These observations come from the same evidence log, separate from the 29-question benchmark.

Needs `GEMINI_API_KEY` and read access to the private upstream repository; the script clones the pinned commit, applies the patch and uses [voice/values.yaml](voice/values.yaml):

```bash
bash docs/labs/05/scripts/voice.sh
```
