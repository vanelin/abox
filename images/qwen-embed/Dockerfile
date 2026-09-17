# llama.cpp server with Qwen3-Embedding-0.6B (Q8_0) baked into the image.
#
# Same shape as images/nomic-embed/Dockerfile: the model ships as an image
# layer so the pod starts without HuggingFace egress and the kubelet caches it.
# Q8_0 rather than f16 on purpose -- it is the exact GGUF ADR-0001 measured
# (Makefile pins its SHA256), so the in-cluster vectors are comparable 1:1.
#
# Built and pushed by .github/workflows/qwen-embed-image.yaml.

ARG LLAMA_IMAGE=ghcr.io/ggml-org/llama.cpp:server-b10920

FROM --platform=$BUILDPLATFORM curlimages/curl:8.11.0 AS fetch

ARG HF_REPO=Qwen/Qwen3-Embedding-0.6B-GGUF
ARG HF_FILE=Qwen3-Embedding-0.6B-Q8_0.gguf

WORKDIR /models
RUN curl -fsSL --retry 5 --retry-delay 3 --retry-connrefused \
      -o /models/model.gguf \
      "https://huggingface.co/${HF_REPO}/resolve/main/${HF_FILE}" \
    && test -s /models/model.gguf

FROM ${LLAMA_IMAGE}
COPY --from=fetch /models/model.gguf /models/model.gguf

# Qwen3-Embedding needs last-token pooling; --embd-normalize -1 returns raw
# vectors so the MCP server can truncate to 256 dims and L2-normalize itself
# (ADR-0001: truncate -> L2). The Deployment overrides these anyway.
CMD ["--host", "0.0.0.0", "--port", "8090", "--embeddings", \
     "--pooling", "last", "--embd-normalize", "-1", \
     "--ctx-size", "16384", "--ubatch-size", "2048", \
     "--model", "/models/model.gguf", "--parallel", "8"]
