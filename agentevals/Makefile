.PHONY: build run serve test vet fmt build-ui dev-backend dev-frontend clean image push

build:
	go build -o bin/agentevals ./cmd/agentevals

run: build
	./bin/agentevals run $(ARGS)

serve: build
	./bin/agentevals serve --ui ui/dist

test:
	go test ./...

vet:
	go vet ./...

fmt:
	gofmt -l .

build-ui:
	cd ui && npm ci && npm run build

dev-backend:
	go run ./cmd/agentevals serve --ui ui/dist

dev-frontend:
	cd ui && npm run dev

clean:
	rm -rf bin ui/dist

# abox: the image releases/agentevals.yaml runs, UI served under /evals.
# Bump the tag on every change to this copy, here and in the release.
IMAGE ?= ghcr.io/vanelin/abox/agentevals-go:54107cf-abox.1

image:
	docker build --build-arg UI_BASE_PATH=/evals/ -t $(IMAGE) .

push: image
	docker push $(IMAGE)
