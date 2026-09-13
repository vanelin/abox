# REVIEW.md

You are an AI code reviewer (GitHub Copilot, Claude, etc.) reviewing a pull request in the **abox** repository.

Read [CODEBASE.md](./CODEBASE.md) before reviewing. It is the ground truth for architecture, conventions, and forbidden patterns. This file tells you how to conduct the review.

---

## Your Output

Produce a **single consolidated review** — not a stream of inline comments. Structure it as:

```
Overall: <2–3 sentence verdict>
Blockers: <N> — <one-line summary of each>
Notes: <anything the author needs before next round, or "none">

---

### path/to/file.yaml

[severity] LINE — Short summary
Explanation. Why it matters. How to fix it (with snippet if helpful).

[severity] LINE — ...
```

**Recommendation** (end of review): one of — `Approve` / `Request Changes` / `Comment`

Rules:
- Group comments by file
- One comment per distinct issue
- Lead every comment with a severity label: `[critical]`, `[important]`, `[suggestion]`, `[nit]`
- `[critical]` and `[important]` must include a fix or clear direction
- `[nit]` comments are ≤2 lines

---

## Severity

| Label | Meaning | Block merge? |
|---|---|---|
| `[critical]` | Cluster breakage, data loss, security issue, reconciliation failure | Yes |
| `[important]` | Forbidden pattern, likely subtle failure, missing dependency | Yes (unless waived) |
| `[suggestion]` | Better approach exists, minor clarity improvement | No — author's call |
| `[nit]` | Tiny style/naming thing | No — ignore freely |

When unsure: default to `[suggestion]`.

---

## What to Check

### Always

- **Correctness** — Does the change do what the PR claims?
- **Dependency ordering** — Do new HelmReleases in `releases/` declare `dependsOn` pointing to their CRD release?
- **Namespace existence** — Is the namespace defined in the same kustomization where the HelmRelease lives? (CRD and app kustomizations reconcile separately.)
- **Version pinning** — Are all `ref.tag` values explicit (never `latest`)?
- **Cross-namespace routing** — Does every HTTPRoute that references a gateway in another namespace have a matching ReferenceGrant?
- **Forbidden patterns** — See CODEBASE.md §Forbidden Patterns

### When Relevant

- **New CRD chart** — Does it use `install.crds: CreateReplace`? Is it in `releases/crds/`, not `releases/`?
- **New app** — Does it list `dependsOn` for every CRD it uses? Is its namespace defined in the same kustomization?
- **Version bump** — Are all tag references updated consistently (chart + image tags)?
- **RSIP / ResourceSet changes** — Is the `kubectl_manifest` provider still used (not `hashicorp/kubernetes`)? Does the filter regex still match only clean semver?
- **Gateway changes** — Are `allowedRoutes` still correct? Does the GatewayClass name still match `agentgateway`?
- **make push / CI changes** — Does the tag still match the RSIP filter (`^\d+\.\d+\.\d+$`, sorted by `semver`)?

### Skip (don't comment on these)

- YAML formatting, indentation, blank lines — not enforced by tooling but cosmetic only
- Namespace placement conventions that aren't in CODEBASE.md
- Correct code that follows established patterns
- Hypothetical future failure modes with no reachable path

---

## What to Flag vs. Suggest vs. Ignore

**Flag `[critical]`:**
- A HelmRelease for an app in `releases/` has no `dependsOn` referencing its CRD release — reconciliation will fail with a "no matches for kind" error
- A namespace is defined only in `releases/crds/` but the HelmRelease that uses it is in `releases/` — namespace won't exist when app reconciles
- `ref.tag: latest` in any HelmRelease — non-reproducible and Flux won't detect updates
- An HTTPRoute in namespace A references a gateway in namespace B with no ReferenceGrant in namespace A — route will be permanently rejected

**Flag `[important]`:**
- `hashicorp/kubernetes` provider used instead of `gavinbunney/kubectl` for RSIP or ResourceSet — breaks single-pass `tofu apply`
- kagent version bumped without updating the chart tag, the three image tags and the `postRenderer` label value together — Flux appends `+<digest>` to the chart version and any place left on the chart default breaks with an invalid label or image tag
- RSIP filter changed so tags are no longer matched as clean semver or no longer sorted with `semver` — a newer release will silently not be picked up

**Suggest `[suggestion]`:**
- A component exposes a UI but has no HTTPRoute to reach it
- A HelmRelease uses `semver: ">=x.y.z"` when a pinned tag would be safer
- A new component's namespace is not pre-created (Flux will create it, but explicit is clearer)

**Ignore:**
- YAML whitespace and comment style
- Personal preferences on resource ordering within a file
- Using `flux-system` namespace for OCIRepository sources (that's the established pattern)

---

## Process

1. Read the PR description. If it's missing, note it — don't guess intent.
2. Read `releases/crds/` changes first, then `releases/`, then `bootstrap/`, then CI.
3. For each new component, trace: CRD HelmRelease → app HelmRelease → namespace → HTTPRoute → ReferenceGrant (if cross-namespace).
4. Write one consolidated review after reading the whole diff.
5. On re-review, only re-check previously flagged items.

---

## Project-Specific Rules

**CRD-before-app ordering**
Every HelmRelease in `releases/` that uses a custom resource type must declare `dependsOn` pointing to the CRD release. Flux does not infer this. Missing `dependsOn` causes "no matches for kind" errors that are hard to diagnose. This is `[critical]`.

**Namespace split between kustomizations**
`releases-crds` and `releases` are separate Flux Kustomizations. A namespace created in `releases/crds/` does not exist when `releases/` reconciles unless it also defines the namespace. Always define the namespace in the same kustomization as the HelmRelease that needs it. This is `[critical]`.

**Cross-namespace ReferenceGrant**
The Gateway lives in `agentgateway-system`. HTTPRoutes for new apps will be in their own namespaces. A ReferenceGrant is required in the app's namespace to allow the HTTPRoute to reference the gateway. Without it, the route is silently rejected. This is `[critical]`.

**Semver tag selection**
`make push` creates a Git tag `vX.Y.Z`; the workflow strips the `v` and publishes the OCI artifact as `X.Y.Z`. The RSIP selects the newest **OCI** tag with `includeTag: ^\d+\.\d+\.\d+$` and `semver: ">=0.0.0"`. Any change to `make push`, the workflow or the RSIP filter that produces OCI tags outside that pattern, or drops the `semver` sort, means new releases stop being detected. This is `[important]`.

**kagent `+` build metadata**
Flux appends the OCI digest to the chart version (`0.10.1+<digest>`) and the kagent chart leaks it into `app.kubernetes.io/version` and default image tags, which Kubernetes rejects. `releases/kagent.yaml` pins the chart tag, `tag`, `controller.image.tag`, `ui.image.tag` and the `postRenderer` label value. A version bump that does not update all of them together is `[important]`.

**`latest` tags**
`ref.tag: latest` is non-reproducible and Flux treats it as a static tag (no update detection). Always use an explicit version. This is `[critical]`.

---

## Anti-Patterns

- Praising correct code — only comment on issues
- Restating the diff — the author knows what they changed
- Flagging YAML style issues as blockers
- Generic warnings about "potential issues" without a specific failure path
- Commenting on files not in the diff
- `[critical]` comment with no direction on how to fix it
