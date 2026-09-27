package judge

import "testing"

func TestDefaultModelFromEnv(t *testing.T) {
	t.Setenv("AGENTEVALS_JUDGE_MODEL", "gemini-test")
	if got := defaultModel(); got != "gemini-test" {
		t.Errorf("defaultModel() = %q, want the env value", got)
	}
	t.Setenv("AGENTEVALS_JUDGE_MODEL", "")
	if got := defaultModel(); got != "gemini-3.8-flash" {
		t.Errorf("defaultModel() = %q, want the fallback", got)
	}
}
