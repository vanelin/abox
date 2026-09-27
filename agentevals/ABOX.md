# Our copy

Upstream [triageagent-dev/evals](https://github.com/triageagent-dev/evals) at `54107cfe6171886072538aaa71797b298060193e`, Apache-2.0 (see LICENSE). Changed for abox:

| File | Change |
|---|---|
| `internal/api/server.go` | the OTLP/HTTP receiver accepts gzip bodies (the OTel Collector's default) |
| `internal/judge/client.go` | default judge from `AGENTEVALS_JUDGE_MODEL`, else `gemini-3.8-flash`; `gemini-2.5-flash` answers 404 for new keys |
| `ui/src/context/TraceProvider.tsx`, `ui/src/components/upload/UploadView.tsx` | UI judge default and list: 3.8 Flash, 3.5 Flash-Lite, 3.1 Pro instead of the closed 2.5/2.0 Flash; the OpenAI and Anthropic options are gone, the judge calls Gemini only |
| `internal/api/otlphttp_test.go`, `internal/judge/default_test.go` | tests for the two server changes |
| `Makefile` | `image` and `push` targets for the image `releases/agentevals.yaml` runs |

Updating: replace this folder with a newer upstream commit and re-apply the rows above; bump the tag in `Makefile` and `releases/agentevals.yaml`. `ui/.gitignore` hides `ui/dist/.gitkeep`, so add it with `git add -f`: without it `go test` fails on a fresh checkout.
