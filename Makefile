help:
	@echo "Available targets:"
	@echo "  run        - Bootstrap the full environment (install tools, provision cluster)"
	@echo "  down       - Destroy the cluster and all resources"
	@echo "  push       - Bump patch version, tag, and push to trigger CI"
	@echo "  tools      - Install necessary tools only"
	@echo "  tofu       - Initialize OpenTofu"
	@echo "  apply      - Apply OpenTofu configuration"
	@echo "  fix-egress - Repair nested-Docker egress (Codespaces) and verify nodes"
	@echo "  fix-docker-acl - Clear the /tmp default ACL that breaks non-root images"
	@echo "  llama      - Build llama-server from a pinned llama.cpp tag into .local/"
	@echo "  models     - Download the ADR-0001 embedding GGUFs into .local/models (checksummed)"
	@echo "  clean-llama - Remove .local/llama.cpp and .local/models"

.PHONY: help run tools fix-egress fix-docker-acl tofu apply down push llama models clean-llama

run:
	@bash scripts/setup.sh

tools:
	@curl -fsSL https://get.opentofu.org/install-opentofu.sh | sh -s -- --install-method standalone
	@curl -sS https://webi.sh/k9s | bash
	@ARCH=$$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/'); \
	  OS=$$(uname -s | tr '[:upper:]' '[:lower:]'); \
	  curl -fsSLo /tmp/kind "https://kind.sigs.k8s.io/dl/v0.33.0/kind-$$OS-$$ARCH" && \
	  sudo install -m 0755 /tmp/kind /usr/local/bin/kind && rm -f /tmp/kind

fix-egress:
	@bash scripts/fix-egress.sh
	@bash scripts/fix-egress.sh verify abox

fix-docker-acl:
	@bash scripts/fix-docker-acl.sh
	@bash scripts/fix-docker-acl.sh verify abox

tofu:
	@cd bootstrap && tofu init

apply:
	@cd bootstrap && tofu apply -auto-approve

down:
	@cd bootstrap && tofu destroy -auto-approve

push:
	@git fetch origin --tags --force
	$(eval TAG=$(shell git tag --list 'v*' | sort -V | tail -1 | sed 's/^v//' || echo "0.0.0"))
	$(eval MAJOR=$(shell echo $(TAG) | cut -d. -f1))
	$(eval MINOR=$(shell echo $(TAG) | cut -d. -f2))
	$(eval PATCH=$(shell echo $(TAG) | cut -d. -f3))
	$(eval NEW_TAG=v$(MAJOR).$(MINOR).$(shell echo $$(($(PATCH)+1))))
	@git tag $(NEW_TAG)
	@git push origin main $(NEW_TAG)
	@echo "Tagged and pushed $(NEW_TAG)"

# Lab 3: local embedding runtime and models. Everything lands under the
# gitignored .local/ and is never called from `make run`. See docs/adr/0001.
LLAMA_TAG  ?= v0.4.0
LLAMA_DIR  := .local/llama.cpp
MODELS_DIR := .local/models
HF         := https://huggingface.co

# name | repo | commit | sha256 (the LFS oid Hugging Face reports as X-Linked-ETag)
MODEL_SPECS := \
  nomic-embed-text-v1.5.Q8_0.gguf|nomic-ai/nomic-embed-text-v1.5-GGUF|0188c9bf409793f810680a5a431e7b899c46104c|3e24342164b3d94991ba9692fdc0dd08e3fd7362e0aacc396a9a5c54a544c3b7 \
  embeddinggemma-300M-Q8_0.gguf|ggml-org/embeddinggemma-300M-GGUF|0f741b5a6585bd53aeb15cd1372c56f2a0f65e12|b5ce9d77a3fc4b3b39ccb5643c36777911cc4eb46a66962eadfa3f5f60490d63 \
  Qwen3-Embedding-0.6B-Q8_0.gguf|Qwen/Qwen3-Embedding-0.6B-GGUF|370f27d7550e0def9b39c1f16d3fbaa13aa67728|06507c7b42688469c4e7298b0a1e16deff06caf291cf0a5b278c308249c3e439

llama:
	@set -e; \
	if [ ! -d $(LLAMA_DIR)/.git ]; then \
	  rm -rf $(LLAMA_DIR); \
	  git clone --depth 1 --branch $(LLAMA_TAG) https://github.com/ggml-org/llama.cpp.git $(LLAMA_DIR); \
	fi; \
	have=$$(git -C $(LLAMA_DIR) describe --tags --exact-match 2>/dev/null || echo none); \
	if [ "$$have" != "$(LLAMA_TAG)" ]; then \
	  echo "llama.cpp checkout is $$have, expected $(LLAMA_TAG); run 'make clean-llama' first"; exit 1; \
	fi; \
	cmake -S $(LLAMA_DIR) -B $(LLAMA_DIR)/build -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=OFF; \
	cmake --build $(LLAMA_DIR)/build --target llama-server -j 2; \
	$(LLAMA_DIR)/build/bin/llama-server --version

models:
	@set -e; mkdir -p $(MODELS_DIR); \
	for spec in $(foreach spec,$(MODEL_SPECS),'$(spec)'); do \
	  name=$${spec%%|*}; rest=$${spec#*|}; repo=$${rest%%|*}; rest=$${rest#*|}; \
	  commit=$${rest%%|*}; sha=$${rest#*|}; dst=$(MODELS_DIR)/$$name; \
	  if [ -f "$$dst" ] && echo "$$sha  $$dst" | sha256sum -c --quiet 2>/dev/null; then \
	    echo "ok       $$name"; continue; \
	  fi; \
	  echo "fetching $$name"; \
	  curl -fL --retry 3 -o "$$dst.part" "$(HF)/$$repo/resolve/$$commit/$$name"; \
	  echo "$$sha  $$dst.part" | sha256sum -c --quiet; \
	  mv "$$dst.part" "$$dst"; \
	done; \
	ls -lh $(MODELS_DIR)/*.gguf

clean-llama:
	@rm -rf $(LLAMA_DIR) $(MODELS_DIR)
	@echo "removed $(LLAMA_DIR) and $(MODELS_DIR)"
