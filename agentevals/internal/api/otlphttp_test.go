package api

import (
	"bytes"
	"compress/gzip"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

// The OTel Collector's otlphttp exporter gzips by default; before the receiver
// decompressed, every such export got a 400.
func TestOTLPTracesHandler_AcceptsGzip(t *testing.T) {
	store := NewSessionStore(nil)
	raw, err := json.Marshal(sampleTracesBody("sess-gzip", "dddd", "span-d"))
	if err != nil {
		t.Fatal(err)
	}
	var buf bytes.Buffer
	gz := gzip.NewWriter(&buf)
	if _, err := gz.Write(raw); err != nil {
		t.Fatal(err)
	}
	if err := gz.Close(); err != nil {
		t.Fatal(err)
	}

	req := httptest.NewRequest(http.MethodPost, "/v1/traces", &buf)
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Content-Encoding", "gzip")
	rec := httptest.NewRecorder()
	otlpTracesHandler(store)(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", rec.Code, rec.Body.String())
	}
	if got := len(store.List()); got != 1 {
		t.Fatalf("got %d sessions, want 1", got)
	}
}
