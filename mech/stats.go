package mech

import (
	"encoding/json"
	"math"
	"os"
)

// Decision counters for the local test harness (explain WHY a change moves the score).
// Active only when MECH_STATS names an output file; read-only with respect to the action.
var (
	statsPath = os.Getenv("MECH_STATS")
	Stats     = map[string]float64{}
	lastTgt   = -1
	firstWep2 = -1.0
	lastT     = -1.0
	// last-alive snapshot (written at match end: for a dead bot, this is its state just before death)
	snapMode            string
	spawnX, spawnY      float64
	spawnSet            bool
	snap                = map[string]float64{}
)

func (b *Brain) record(o *Obs, act *Action) {
	if statsPath == "" {
		return
	}
	dt := 0.05
	if lastT >= 0 && o.T > lastT {
		dt = o.T - lastT
	}
	lastT = o.T
	Stats["s_mode:"+b.Mode] += dt
	if b.retreat {
		Stats["s_retreat"] += dt
	}
	if b.pracOn {
		Stats["s_practice_params"] += dt
	}
	if b.notPractice && Stats["t_ffa_detected"] == 0 {
		Stats["t_ffa_detected"] = o.T
	}
	me := &o.Self
	for i, w := range me.Weapons {
		if w != nil && i < 2 && act.Fire[i] {
			Stats["fire_ticks:"+w.Kind]++
		}
	}
	if firstWep2 < 0 && len(me.Weapons) > 1 && me.Weapons[1] != nil {
		firstWep2 = o.T
		Stats["t_second_weapon"] = o.T
	}
	if b.stickAt == o.T && b.stickID != lastTgt {
		if lastTgt >= 0 {
			Stats["target_switch"]++
		}
		lastTgt = b.stickID
	}
	for i := range o.Events {
		e := &o.Events[i]
		switch e.Type {
		case "hit":
			Stats["hit_n:"+e.Weapon]++
			Stats["hit_dmg:"+e.Weapon] += e.Amount
			if e.Weapon == "gun" {
				if t := b.tracks[e.Target]; t != nil {
					band := "near"
					if t.Dist >= 100 {
						band = "far"
					} else if t.Dist >= 60 {
						band = "mid"
					}
					Stats["gunhit:mech:"+band]++
				} else if b.npcs[e.Target] != nil {
					Stats["gunhit:npc"]++
				} else {
					Stats["gunhit:other"]++
				}
			}
		case "damaged":
			src := e.Weapon
			if src == "" {
				src = "other"
			}
			Stats["taken:"+src] += e.Amount
		case "kill":
			Stats["kills"]++
			Stats["kill_t_last"] = o.T
		case "took":
			Stats["took"]++
		case "upgrade":
			Stats["upgrades"]++
		}
	}
	if !spawnSet {
		spawnX, spawnY, spawnSet = me.Pos[0], me.Pos[1], true
	}
	nSeen, nearest := 0.0, 1e9
	for _, t := range b.tracks {
		if t.Seen == o.T {
			nSeen++
			nearest = math.Min(nearest, t.Dist)
			if Stats["t_first_enemy_seen"] == 0 {
				Stats["t_first_enemy_seen"] = o.T
			}
		}
	}
	for i := range o.Events {
		if o.Events[i].Type == "damaged" && o.Events[i].By != nil && Stats["t_first_damaged"] == 0 {
			Stats["t_first_damaged"] = o.T
		}
	}
	if (act.Fire[0] || act.Fire[1]) && Stats["t_first_fire"] == 0 {
		Stats["t_first_fire"] = o.T
	}
	snapMode = b.Mode
	snap["end_hp_frac"] = me.HP / math.Max(1, me.MaxHP)
	snap["end_seen_enemies"] = nSeen
	snap["end_nearest_enemy"] = nearest
	snap["end_dist_spawn"] = math.Hypot(me.Pos[0]-spawnX, me.Pos[1]-spawnY)
	snap["end_dist_zone_center"] = math.Hypot(me.Pos[0]-o.Zone.Center[0], me.Pos[1]-o.Zone.Center[1])
	snap["end_zone_radius"] = o.Zone.Radius
	snap["spawn_dist_zone_center"] = math.Hypot(spawnX-o.Zone.Center[0], spawnY-o.Zone.Center[1])
	Stats["gate_held"] = float64(b.gateHeld)
	Stats["lead_damped"] = float64(b.leadDamped)
	Stats["aim_held"] = float64(b.aimHeld)
	Stats["panics"] = float64(b.Panics)
	Stats["t_last"] = o.T
	Stats["cubes"] = float64(me.Cubes)
}

// logGunShot records each gun trigger by target type, distance band and aim error (harness only).
// Pitch/yaw error = wanted (lead) - actual torso aim at the decision; bands: <60, 60-100, >=100 m.
func (b *Brain) logGunShot(isMech, isNpc bool, dist, wantP, haveP, wantY, haveY float64) {
	if statsPath == "" {
		return
	}
	kind := "crate"
	if isMech {
		kind = "mech"
	} else if isNpc {
		kind = "npc"
	}
	band := "near"
	if dist >= 100 {
		band = "far"
	} else if dist >= 60 {
		band = "mid"
	}
	k := "shot:" + kind + ":" + band
	Stats[k]++
	if isMech {
		ep := (wantP - haveP) * 180 / math.Pi
		ey := math.Abs(angDiff(wantY, haveY)) * 180 / math.Pi
		Stats[k+":pitch_err_sum"] += ep
		Stats[k+":abs_pitch_err_sum"] += math.Abs(ep)
		Stats[k+":abs_yaw_err_sum"] += ey
		if math.Abs(ep) > 1 {
			Stats[k+":pitch_err_gt1"]++
		}
	}
}

// WriteStats flushes the counters at match end (no-op outside the harness).
func WriteStats() {
	if statsPath == "" {
		return
	}
	for k, v := range snap {
		Stats[k] = v
	}
	if snapMode != "" {
		Stats["end_mode:"+snapMode] = 1
	}
	if raw, err := json.Marshal(Stats); err == nil {
		os.WriteFile(statsPath, raw, 0o644)
	}
}
