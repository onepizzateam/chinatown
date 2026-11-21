"""Ground navigation over the baked waypoint graph (tools/bake_nav.py).

Path queries are table lookups: nearest waypoint to me, nearest to the goal, then follow
nxt[goal, current] hop by hop. Between waypoints we steer straight (edges were checked clear),
and we skip ahead to any later waypoint we can already walk to in a straight line.
"""
from math import hypot
from pathlib import Path
import numpy as np

DATA = Path(__file__).resolve().parent / "data" / "nav.npz"


class Nav:
    def __init__(self, world, path=DATA):
        N = np.load(path)
        self.world = world
        self.wp = N["wp"]
        self.dist = N["dist"]
        self.nxt = N["nxt"]
        self.cellwp = N["cellwp"]
        self.minX, self.minY, self.step, self.cs = (float(v) for v in N["meta"])
        self.cs = int(self.cs)

    def nearest_wp(self, x, y):
        ci = int(round((x - self.minX) / (self.step * self.cs)))
        cj = int(round((y - self.minY) / (self.step * self.cs)))
        H, W = self.cellwp.shape
        for r in range(0, 4):
            best, bd = -1, 1e18
            for dj in range(-r, r + 1):
                for di in range(-r, r + 1):
                    if max(abs(di), abs(dj)) != r:
                        continue
                    i, j = ci + di, cj + dj
                    if 0 <= i < W and 0 <= j < H:
                        k = int(self.cellwp[j, i])
                        if k >= 0:
                            d = hypot(self.wp[k, 0] - x, self.wp[k, 1] - y)
                            if d < bd:
                                best, bd = k, d
            if best >= 0:
                return best
        d = np.hypot(self.wp[:, 0] - x, self.wp[:, 1] - y)
        return int(np.argmin(d))

    def path_len(self, a, b):
        """Ground path length between two points via waypoints (inf if unreachable)."""
        s, g = self.nearest_wp(*a), self.nearest_wp(*b)
        return float(self.dist[s, g]) + hypot(a[0] - self.wp[s, 0], a[1] - self.wp[s, 1]) + \
            hypot(b[0] - self.wp[g, 0], b[1] - self.wp[g, 1])

    def route(self, start, goal, max_hops=64):
        """List of (x, y) waypoints from start to goal (goal appended last). [] if unreachable."""
        s, g = self.nearest_wp(*start), self.nearest_wp(*goal)
        if not np.isfinite(self.dist[s, g]):
            return []
        out, cur = [], s
        for _ in range(max_hops):
            out.append((float(self.wp[cur, 0]), float(self.wp[cur, 1])))
            if cur == g:
                break
            cur = int(self.nxt[g, cur])
            if cur < 0:
                break
        out.append((float(goal[0]), float(goal[1])))
        return out

    def straight_ok(self, a, b):
        d = hypot(b[0] - a[0], b[1] - a[1])
        n = max(2, int(d) + 1)
        w = self.world
        for k in range(n + 1):
            t = k / n
            i, j = w.cell(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
            if not w.clear[j, i]:
                return False
        return True

    def steer(self, pos, route, lookahead=4):
        """Direction (unit 2-vector) toward the furthest of the next few route points we can walk to straight."""
        if not route:
            return (0.0, 0.0)
        target = route[0]
        for p in route[:lookahead]:
            if self.straight_ok(pos, p):
                target = p
        dx, dy = target[0] - pos[0], target[1] - pos[1]
        d = hypot(dx, dy)
        return (dx / d, dy / d) if d > 1e-6 else (0.0, 0.0)
