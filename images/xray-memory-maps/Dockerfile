# The maps image xray-memory's chart mounts as an image volume and seeds its
# claim from (releases/xray-memory.yaml, snapshots.seed.images). Nothing runs
# from it: it is a carrier for <label>.graph.gob.gz files under /maps.
#
# maps/ is not in git. .github/workflows/xray-memory-maps-image.yaml builds it
# from docs/labs/05/*.catalog.json right before this build, because a map is
# derived -- catalog + embedder in, snapshot out -- and the catalog is the
# source of truth.
#
# 65532 is the distroless nonroot uid the server runs as; it rewrites its
# worked copy of a map on every flush, so the seeded file must be its own.
FROM scratch
COPY --chown=65532:65532 maps/ /maps/
