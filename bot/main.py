"""Mech Royale bot v1: aggressive economy with zone discipline.

Design choices come from official (not simulated) results that other teams published:
- practice rewards fighting: never-retreat and fight-at-~110 m bots scored best; 33 of 42
  analysed deaths happened while retreating across open ground;
- economy pays: farm crates, drones and supply drops, and take HP/armor upgrades first;
- laser first (+0.14); quiet movement hurt, so we move at full speed.

Every tunable number lives in P so the optimiser (NTBEA) can search it.
"""
import os
import sys
import time
from math import atan2, cos, hypot, pi, sin

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mechfight as mf  # noqa: E402
from ballistics import gun_aim, mortar_aim, wrap  # noqa: E402
from nav import Nav  # noqa: E402
from world import World  # noqa: E402

P = {
    "fight_range": 110.0,      # preferred gun distance
    "engage_range": 190.0,     # start fights inside this
    "retreat_hp": 0.18,        # only disengage below this HP fraction ...
    "retreat_ratio": 2.2,      # ... and when the enemy has this much more HP than us
    "jink_period": 0.6,        # strafe direction change, seconds (house bots: 0.6 s)
    "loot_radius": 120.0,      # go for weapons/cubes/crates within this path length
    "zone_margin": 25.0,       # stay this far inside the circle we are heading to
    "drop_radius": 160.0,      # chase supply drops within this distance
    "w_laser": 3.6, "w_lightning": 3.0, "w_mortar": 1.5,
}
UPGRADE_ORDER = ["plating", "armor", "nanites", "laser_damage", "gun_damage", "laser_charge",
                 "gun_rate", "lightning_efficiency", "gyros", "servos", "capacitor", "reactor",
                 "gun_mag", "gun_velocity", "lightning_range", "lightning_chain", "sensors",
                 "mortar_reload", "mortar_velocity", "mortar_splash", "jets", "laser_pierce"]


def unit(dx, dy):
    d = hypot(dx, dy)
    return (dx / d, dy / d) if d > 1e-9 else (0.0, 0.0)


class Bot:
    name = "pizza-mech"

    def __init__(self, hello):
        self.cfg = hello["config"]
        self.world = World()
        self.nav = Nav(self.world)
        self.route, self.route_goal, self.route_t = [], None, -1.0
        self.jink_sign, self.jink_t = 1, 0.0
        self.my_kills = 0
        self.others_dead_not_me = 0
        self.last_alive = 16
        self.ffa = False
        self.charging_since = None
        self.last_damage_t = -99.0

    # --- helpers ------------------------------------------------------------------------
    def zone_goal(self, obs):
        z = obs["zone"]
        t = obs["t"]
        # Head for the next circle once the shrink is near; otherwise stay inside the current one.
        cx, cy, r = (z["next_center"][0], z["next_center"][1], z["next_radius"]) \
            if t > z["shrink_start"] - 25 else (z["center"][0], z["center"][1], z["radius"])
        return cx, cy, max(5.0, r - P["zone_margin"])

    def go(self, obs, goal):
        me = obs["self"]["pos"]
        t = obs["t"]
        if self.route_goal is None or hypot(goal[0] - self.route_goal[0], goal[1] - self.route_goal[1]) > 8 \
                or t - self.route_t > 2.0:
            self.route = self.nav.route((me[0], me[1]), goal)
            self.route_goal, self.route_t = goal, t
        while len(self.route) > 1 and hypot(self.route[0][0] - me[0], self.route[0][1] - me[1]) < 6:
            self.route.pop(0)
        return self.nav.steer((me[0], me[1]), self.route) if self.route else unit(goal[0] - me[0], goal[1] - me[1])

    def weapon(self, me, kind):
        for i, w in enumerate(me["weapons"]):
            if w and w["kind"] == kind:
                return i, w
        return None, None

    # --- decision -----------------------------------------------------------------------
    def act(self, obs):
        me = obs["self"]
        pos, t = me["pos"], obs["t"]
        hp_frac = me["hp"] / me["max_hp"]
        act = {"fire": [False, False]}

        for e in obs.get("events", []):
            if e["type"] == "kill":
                self.my_kills += 1
            elif e["type"] == "damaged":
                self.last_damage_t = t
        # Mode detection: in practice house bots only die to us, the zone or drones; early
        # deaths we did not cause mean other bots are fighting each other (free-for-all).
        dead = 16 - obs["alive"]
        if dead > self.my_kills and t < 150 and obs["zone"]["dps"] < 40:
            self.others_dead_not_me = dead - self.my_kills
            if self.others_dead_not_me >= 2:
                self.ffa = True

        if obs.get("offer"):
            ids = [c["id"] for c in obs["offer"]["choices"]]
            rank = {u: i for i, u in enumerate(UPGRADE_ORDER)}
            act["pick"] = min(range(len(ids)), key=lambda i: rank.get(ids[i], 99))

        # Pick up better weapons when standing on them.
        held = {w["kind"] for w in me["weapons"] if w}
        wval = {"laser": P["w_laser"], "lightning": P["w_lightning"], "mortar": P["w_mortar"], "gun": 1.0}
        for pk in obs.get("pickups", []):
            if hypot(pk["pos"][0] - pos[0], pk["pos"][1] - pos[1]) <= 3.8 and abs(pk["pos"][2] - pos[2]) < 4 \
                    and pk["kind"] not in held:
                slot1 = me["weapons"][1]
                if slot1 is None:
                    act["take"] = pk["id"]
                elif wval[pk["kind"]] > wval[slot1["kind"]] and not (slot1["kind"] == "laser" and slot1.get("charge", 0) > 0):
                    act["take"], act["drop"] = pk["id"], 1
                break

        enemies = [m for m in obs["mechs"] if m["kind"] == "mech"]
        npcs = [m for m in obs["mechs"] if m["kind"] == "npc"]
        target = None
        if enemies:
            def score(m):
                d = hypot(m["pos"][0] - pos[0], m["pos"][1] - pos[1])
                return d * (0.5 + m.get("hp", 1400) / max(1.0, m.get("max_hp", 1400)))
            target = min(enemies, key=score)
        tdist = hypot(target["pos"][0] - pos[0], target["pos"][1] - pos[1]) if target else 1e9

        # --- movement ----------------------------------------------------------------
        zx, zy, zr = self.zone_goal(obs)
        outside = hypot(pos[0] - zx, pos[1] - zy) > zr
        move = (0.0, 0.0)
        boost = False
        if outside and (obs["zone"]["dps"] >= 60 or not target or not me["in_zone"]):
            move = self.go(obs, (zx, zy)); boost = me["energy"] > 25
        elif target and tdist < P["engage_range"]:
            losing = hp_frac < P["retreat_hp"] and target.get("hp", 0) > P["retreat_ratio"] * me["hp"]
            if self.ffa and len(enemies) >= 2 and hp_frac < 0.6:
                losing = True
            to = unit(target["pos"][0] - pos[0], target["pos"][1] - pos[1])
            if t - self.jink_t > P["jink_period"]:
                self.jink_sign, self.jink_t = -self.jink_sign, t
            side = (-to[1] * self.jink_sign, to[0] * self.jink_sign)
            if losing:
                away = self.go(obs, (zx, zy))
                move = unit(away[0] + 0.5 * side[0], away[1] + 0.5 * side[1]); boost = True
            else:
                radial = 0.7 if tdist > P["fight_range"] + 20 else (-0.5 if tdist < P["fight_range"] - 30 else 0.0)
                move = unit(to[0] * radial + side[0], to[1] * radial + side[1])
        else:
            goal = self.pick_goal(obs, held, wval)
            move = self.go(obs, goal) if goal else self.go(obs, (zx, zy))
            boost = me["energy"] > 60 and goal is not None
        act["move"] = [move[0], move[1]]
        act["boost"] = bool(boost)

        # --- aiming and firing --------------------------------------------------------
        aim_t = target or self.nearest(npcs + [dict(pos=c["pos"], vel=[0, 0, 0], kind="crate") for c in obs.get("crates", [])], pos, 120)
        if aim_t is not None:
            self.shoot(obs, me, aim_t, act)
        else:
            act["aim"] = [atan2(move[1], move[0]) if move != (0.0, 0.0) else me["aim"][0], 0.0]
            gi, g = self.weapon(me, "gun")
            if g and g["ammo"] < g["stats"]["mag"] * 0.5 and g["reload"] == 0:
                act["reload"] = True
        return act

    def nearest(self, things, pos, maxd):
        best, bd = None, maxd
        for x in things:
            d = hypot(x["pos"][0] - pos[0], x["pos"][1] - pos[1])
            if d < bd:
                best, bd = x, d
        return best

    def pick_goal(self, obs, held, wval):
        me = obs["self"]
        pos = me["pos"]
        best, bs = None, 0.0
        slot1 = me["weapons"][1]
        for pk in obs.get("pickups", []):
            gain = wval[pk["kind"]] - (wval[slot1["kind"]] if slot1 else 0)
            if pk["kind"] in held or gain <= 0:
                continue
            d = hypot(pk["pos"][0] - pos[0], pk["pos"][1] - pos[1])
            if d < P["loot_radius"] and gain * 100 / (d + 20) > bs:
                best, bs = (pk["pos"][0], pk["pos"][1]), gain * 100 / (d + 20)
        for c in obs.get("cubes", []):
            d = hypot(c["pos"][0] - pos[0], c["pos"][1] - pos[1])
            if d < P["loot_radius"] and 150 / (d + 20) > bs:
                best, bs = (c["pos"][0], c["pos"][1]), 150 / (d + 20)
        for dr in obs.get("drops", []):
            d = hypot(dr["pos"][0] - pos[0], dr["pos"][1] - pos[1])
            if d < P["drop_radius"] and dr["lands_in"] < d / 12 + 2 and 400 / (d + 20) > bs:
                best, bs = (dr["pos"][0], dr["pos"][1]), 400 / (d + 20)
        for c in obs.get("crates", []):
            d = hypot(c["pos"][0] - pos[0], c["pos"][1] - pos[1])
            if d < P["loot_radius"] and abs(c["pos"][2] - pos[2]) < 3 and 60 / (d + 20) > bs:
                best, bs = (c["pos"][0], c["pos"][1]), 60 / (d + 20)
        return best

    def shoot(self, obs, me, tgt, act):
        pos = me["pos"]
        st = me["stats"]
        R = st.get("radius", 2.5)
        cur_yaw, cur_pitch = me["aim"]
        tvel = tgt.get("vel", [0, 0, 0])
        center_h = 4.5 if tgt.get("kind") == "mech" else (1.75 if tgt.get("kind") == "npc" else 0.5)
        dist = hypot(tgt["pos"][0] - pos[0], tgt["pos"][1] - pos[1])
        gi, g = self.weapon(me, "gun")
        speed = g["stats"]["speed"] if g else 252.0
        yaw, pitch, _ = gun_aim(pos, cur_yaw, st.get("muzzle_height", 7.0), R, tgt["pos"], tvel, center_h, speed)
        act["aim"] = [yaw, pitch]
        on = abs(wrap(cur_yaw - yaw)) * max(dist, 1) < 2.0 and abs(cur_pitch - pitch) * max(dist, 1) < 3.5
        fire = [False, False]
        for i, w in enumerate(me["weapons"]):
            if not w:
                continue
            k, s = w["kind"], w["stats"]
            if k == "gun":
                fire[i] = on and dist < s["range"] and w["ammo"] > 0 and w["reload"] == 0
                if w["ammo"] == 0 and w["reload"] == 0:
                    act["reload"] = True
            elif k == "laser":
                if w.get("charge", 0) > 0:
                    # Keep charging until full, then release when on target.
                    fire[i] = not (w["charge"] >= s["charge"] * 0.98 and on)
                else:
                    fire[i] = w["cooldown"] == 0 and dist < s["range"] and tgt.get("kind") != "crate"
            elif k == "lightning":
                fire[i] = dist < s["range"] and abs(wrap(cur_yaw - yaw)) < s["cone_deg"] * pi / 360 and \
                    me["energy"] > s.get("energy", 3) + 10 and w["cooldown"] == 0
            elif k == "mortar":
                if 45 < dist < 220 and w["cooldown"] == 0:
                    m = mortar_aim(pos, cur_yaw, st.get("height", 9) + 0.5, R, tgt["pos"], tvel,
                                   s["speed"], s.get("gravity", 22), high=dist < 120)
                    if m and abs(wrap(cur_yaw - m[0])) < 0.05 and abs(cur_pitch - m[1]) < 0.05:
                        fire[i] = True
                    elif m and not any(fire) and (g is None or g["ammo"] == 0):
                        act["aim"] = [m[0], m[1]]
        act["fire"] = fire


if __name__ == "__main__":
    mf.run(Bot)
