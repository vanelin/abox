package tools

import (
	"math"
	"testing"
)

func TestMRL(t *testing.T) {
	full := []float64{3, 4, 100, 100}

	if got := mrl(full, 0); len(got) != 4 {
		t.Fatalf("dims=0 must keep the full vector, got %d", len(got))
	}
	if got := mrl(full, 8); len(got) != 4 {
		t.Fatalf("dims beyond length must keep the full vector, got %d", len(got))
	}

	got := mrl([]float64{3, 4, 100, 100}, 2)
	if len(got) != 2 {
		t.Fatalf("want 2 dims, got %d", len(got))
	}
	// 3,4 -> 0.6,0.8: unit length after truncation, not before.
	if math.Abs(got[0]-0.6) > 1e-9 || math.Abs(got[1]-0.8) > 1e-9 {
		t.Fatalf("want [0.6 0.8], got %v", got)
	}
}
