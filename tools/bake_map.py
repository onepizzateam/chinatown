"""Bake the static arena into compact numpy rasters for the bot (run once, offline).

Output: bot/data/map.npz with, on a 1 m grid aligned to the terrain vertex grid
(x = minX + i, y = minY + j, arrays indexed [j, i]):
  ground    float32  terrain height (m)
  solid_lo  float32  lowest prism base over the cell (+inf if none)
  solid_hi  float32  highest prism top over the cell (-inf if none)
  walk      bool     a standing mech centre can be here at ground level
                     (no solid between ground+step_up and ground+mech height, slope ok)
  clear     bool     walk, and no blocked cell within the mech radius (2.5 m)
  canopy    float32  summed crown thickness proxy for soft vision blocking (m)
  trunk     bool     a tree trunk occupies the cell (blocks sight, not shots or movement)

Usage: python tools/bake_map.py <arena_dir> <out.npz>
"""
import json, sys
import numpy as np

STEP_UP = 1.2      # protocol mech.step_up
MECH_H = 9.0       # protocol: cylinder height
RADIUS = 2.5       # protocol: cylinder radius
SLOPE_MAX = 1.6    # m per m on a smoothed surface; the server lets bots over LiDAR spikes steeper than tan 50


def raster_polygon(xs, ys, ring):
    """Even-odd point-in-polygon for cell centres xs (nx,) ys (ny,) -> bool (ny, nx)."""
    px = np.asarray(ring[0::2], dtype=np.float64)
    py = np.asarray(ring[1::2], dtype=np.float64)
    X, Y = np.meshgrid(xs, ys)
    inside = np.zeros(X.shape, dtype=bool)
    qx, qy = np.roll(px, 1), np.roll(py, 1)
    for x1, y1, x2, y2 in zip(px, py, qx, qy):
        cond = (y1 > Y) != (y2 > Y)
        if not cond.any():
            continue
        xint = (x2 - x1) * (Y - y1) / ((y2 - y1) if y2 != y1 else 1e-12) + x1
        inside ^= cond & (X < xint)
    return inside


def dilate(mask, r):
    """Binary dilation of mask by a disc of radius r cells (square shifts, no scipy)."""
    out = mask.copy()
    R = int(np.ceil(r))
    ny, nx = mask.shape
    for dj in range(-R, R + 1):
        for di in range(-R, R + 1):
            if di * di + dj * dj > r * r or (di == 0 and dj == 0):
                continue
            src = mask[max(0, -dj):ny - max(0, dj), max(0, -di):nx - max(0, di)]
            out[max(0, dj):ny - max(0, -dj), max(0, di):nx - max(0, -di)] |= src
    return out


def main(arena, out):
    w = json.load(open(f"{arena}/v2/world.json"))
    t = w["terrain"]
    nx, ny, step = t["nx"], t["ny"], t["step"]
    minX, minY = t["minX"], t["minY"]
    ground = np.fromfile(f"{arena}/v2/{t['file']}", dtype="<i2").reshape(ny, nx).astype(np.float32) * t["scale"]
    xs = minX + np.arange(nx) * step
    ys = minY + np.arange(ny) * step

    solid_lo = np.full((ny, nx), np.inf, dtype=np.float32)
    solid_hi = np.full((ny, nx), -np.inf, dtype=np.float32)
    blocked = np.zeros((ny, nx), dtype=bool)
    for p in w["prisms"]:
        ring = p["ring"]
        rx, ry = ring[0::2], ring[1::2]
        i0 = max(0, int(np.floor((min(rx) - minX) / step)) - 1)
        i1 = min(nx, int(np.ceil((max(rx) - minX) / step)) + 2)
        j0 = max(0, int(np.floor((min(ry) - minY) / step)) - 1)
        j1 = min(ny, int(np.ceil((max(ry) - minY) / step)) + 2)
        if i1 <= i0 or j1 <= j0:
            continue
        m = raster_polygon(xs[i0:i1], ys[j0:j1], ring)
        for h in p.get("holes") or []:
            m &= ~raster_polygon(xs[i0:i1], ys[j0:j1], h)
        if not m.any():
            continue
        sl = (slice(j0, j1), slice(i0, i1))
        solid_lo[sl] = np.where(m, np.minimum(solid_lo[sl], p["base"]), solid_lo[sl])
        solid_hi[sl] = np.where(m, np.maximum(solid_hi[sl], p["top"]), solid_hi[sl])
        g = ground[sl]
        # A prism blocks a ground-level mech if it overlaps [ground + step_up, ground + height].
        blocked[sl] |= m & (p["base"] < g + MECH_H) & (p["top"] > g + STEP_UP)

    # Slope on a lightly smoothed surface (3x3 mean).
    gs = ground.copy()
    gs[1:-1, 1:-1] = sum(ground[1 + dj:ny - 1 + dj, 1 + di:nx - 1 + di] for dj in (-1, 0, 1) for di in (-1, 0, 1)) / 9
    gy, gx = np.gradient(gs, step)
    steep = np.hypot(gx, gy) > SLOPE_MAX

    walk = ~blocked & ~steep
    walk[0, :] = walk[-1, :] = walk[:, 0] = walk[:, -1] = False
    clear = ~dilate(~walk, RADIUS / step)

    tr = w["trees"]
    f = {k: i for i, k in enumerate(tr["fields"])}
    data = np.asarray(tr["data"], dtype=np.float64).reshape(-1, len(tr["fields"]))
    canopy = np.zeros((ny, nx), dtype=np.float32)
    trunk = np.zeros((ny, nx), dtype=bool)
    for row in data:
        cx = row[f["crownX"]] if "crownX" in f and not np.isnan(row[f["crownX"]]) else row[f["x"]]
        cy = row[f["crownY"]] if "crownY" in f and not np.isnan(row[f["crownY"]]) else row[f["y"]]
        cr, crown_h = row[f["crownR"]], row[f["height"]] - row[f["crownBase"]]
        i, j = int(round((cx - minX) / step)), int(round((cy - minY) / step))
        R = int(np.ceil(cr))
        jj, ii = np.ogrid[max(0, j - R):min(ny, j + R + 1), max(0, i - R):min(nx, i + R + 1)]
        d2 = ((ii - i) * step) ** 2 + ((jj - j) * step) ** 2
        canopy[jj, ii] += np.where(d2 <= cr * cr, crown_h, 0).astype(np.float32)
        ti, tj = int(round((row[f["x"]] - minX) / step)), int(round((row[f["y"]] - minY) / step))
        if 0 <= ti < nx and 0 <= tj < ny:
            trunk[tj, ti] = True

    np.savez_compressed(out, ground=ground, solid_lo=solid_lo, solid_hi=solid_hi, walk=walk, clear=clear,
                        canopy=canopy, trunk=trunk,
                        meta=np.array([minX, minY, step, nx, ny], dtype=np.float64))
    print(f"baked {nx}x{ny}: walk {walk.mean():.3f} clear {clear.mean():.3f} "
          f"solid cells {(solid_hi > -np.inf).mean():.3f} canopy cells {(canopy > 0).mean():.3f}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
