package api

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestAuthMeHandler_AuthDisabled(t *testing.T) {
	handler := authMeHandler("", nil)
	req := httptest.NewRequest(http.MethodGet, "/auth/me", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Errorf("status = %d, want 200", rec.Code)
	}
	var body struct {
		Authenticated bool  `json:"authenticated"`
		AuthEnabled   *bool `json:"authEnabled"`
	}
	if err := json.NewDecoder(rec.Body).Decode(&body); err != nil {
		t.Fatalf("decoding response: %v", err)
	}
	if body.Authenticated || body.AuthEnabled == nil || *body.AuthEnabled {
		t.Errorf("body = %+v, want authenticated=false authEnabled=false", body)
	}
}
