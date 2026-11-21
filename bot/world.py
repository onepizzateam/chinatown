"""Static world model: baked rasters (tools/bake_map.py) plus fast line-of-sight queries."""
from pathlib import Path
import numpy as np

DATA = Path(__file__).resolve().parent / "data" / "map.npz"


class World:
    def __init__(self, path=DATA):
        M = np.load(path)
        self.minX, self.minY, self.step, nx, ny = (float(v) for v in M["meta"])
        self.nx, self.ny = int(nx), int(ny)
        self.ground = M["ground"]
        self.lo = M["solid_lo"]
        self.hi = M["solid_hi"]
        self.walk = M["walk"]
        self.clear = M["clear"]
        self.canopy = M["canopy"]
        self.trunk = M["trunk"]
        self.maxX = self.minX + (self.nx - 1) * self.step
        self.maxY = self.minY + (self.ny - 1) * self.step

    # --- cell helpers -------------------------------------------------------------------
    def cell(self, x, y):
        i = int(round((x - self.minX) / self.step))
        j = int(round((y - self.minY) / self.step))
        return min(max(i, 0), self.nx - 1), min(max(j, 0), self.ny - 1)

    def ground_at(self, x, y):
        i, j = self.cell(x, y)
        return float(self.ground[j, i])

    def support_at(self, x, y, feet_z):
        """Surface height a mech with feet at feet_z would stand on (roof top or ground)."""
        i, j = self.cell(x, y)
        hi = float(self.hi[j, i])
        return hi if hi > -1e9 and hi <= feet_z + 1.2 else float(self.ground[j, i])

    # --- line of sight ------------------------------------------------------------------
    def _samples(self, a, b, spacing):
        d = np.subtract(b, a)
        L = float(np.sqrt((d * d).sum()))
        n = max(2, int(L / spacing) + 1)
        t = np.linspace(0.0, 1.0, n)[1:-1]
        pts = np.asarray(a)[None, :] + t[:, None] * d[None, :]
        i = np.clip(np.rint((pts[:, 0] - self.minX) / self.step).astype(np.int32), 0, self.nx - 1)
        j = np.clip(np.rint((pts[:, 1] - self.minY) / self.step).astype(np.int32), 0, self.ny - 1)
        return pts[:, 2], i, j, L

    def blocked(self, a, b, spacing=1.0):
        """True if terrain or a building blocks the straight segment a -> b (3-tuples)."""
        z, i, j, _ = self._samples(a, b, spacing)
        if z.size == 0:
            return False
        if (z < self.ground[j, i] - 0.2).any():
            return True
        return bool(((z >= self.lo[j, i]) & (z <= self.hi[j, i])).any())

    def canopy_cover(self, a, b, spacing=1.0):
        """Crown metres a sight line passes through (soft vision block; shots go through)."""
        z, i, j, L = self._samples(a, b, spacing)
        if z.size == 0:
            return 0.0
        c = self.canopy[j, i]
        return float((c > 0).sum() * (L / (z.size + 1)))

    def sees(self, eye, target, canopy_limit=4.0):
        """Approximate server vision test between two points (buildings hard, canopy soft)."""
        return not self.blocked(eye, target) and self.canopy_cover(eye, target) < canopy_limit
