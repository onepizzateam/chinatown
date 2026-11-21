package mech

import (
	"encoding/json"
	"os"
)

// Tuning hook for the local test harness. MECH_P overrides base parameters and MECH_SQ overrides the
// practice-mode (squad) parameters, each as a JSON object of Params fields, e.g. MECH_SQ='{"Stick":150}'.
// Both are unset in the submitted container, so the shipped behavior is exactly the compiled defaults.
var envOverrides = map[string][]byte{}

// Salt re-seeds the bot's random choices (home spots, unstuck moves) without changing any logic.
// 0 = the unsalted bot.
var Salt int64 = 2

func init() {
	for _, k := range []string{"MECH_P", "MECH_SQ"} {
		if v := os.Getenv(k); v != "" {
			envOverrides[k] = []byte(v)
		}
	}
}

func applyEnv(p Params, key string) Params {
	if raw, ok := envOverrides[key]; ok {
		json.Unmarshal(raw, &p)
	}
	return p
}
