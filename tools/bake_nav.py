"""Bake a ground waypoint graph with all-pairs routing tables (offline; needs scipy).

Run-time path queries then cost a table lookup per hop instead of an A* search, which keeps the
bot far inside its 50 ms budget on one CPU.

Output: bot/data/nav.npz
  wp       float32 (N, 2)   waypoint x, y (on 'clear' cells)
  dist     float32 (N, N)   shortest ground path length between waypoints (inf if unreachable)
  nxt      int16   (N, N)   nxt[g, s] = the neighbour of s on a shortest path from s to g (-1 if none)
  cellwp   int16   (ny/4, nx/4)  nearest waypoint reachable in a straight clear line from each 4 m cell (-1 if none)

Usage: python tools/bake_nav.py bot/data/map.npz bot/data/nav.npz [spacing_m] [link_m]
"""
import sys
import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import shortest_path


def straight_clear(clear, minX, minY, step, a, b, spacing=1.0):
    d = np.subtract(b, a)
    L = float(np.hypot(*d))
    n = max(2, int(L / spacing) + 1)
    t = np.linspace(0, 1, n)
    x = a[0] + t * d[0]
    y = a[1] + t * d[1]
    i = np.rint((x - minX) / step).astype(int)
    j = np.rint((y - minY) / step).astype(int)
    return bool(clear[j, i].all())


def main(map_path, out, spacing=16.0, link=40.0):
    M = np.load(map_path)
    minX, minY, step, nx, ny = M["meta"]
    nx, ny = int(nx), int(ny)
    clear = M["clear"]

    # Waypoints: a jittered lattice, each snapped to the clear cell nearest its lattice point.
    pts = []
    for y in np.arange(minY + spacing / 2, minY + ny * step, spacing):
        for x in np.arange(minX + spacing / 2, minX + nx * step, spacing):
            i0, j0 = int((x - minX) / step), int((y - minY) / step)
            r = int(spacing / 2)
            win = clear[max(0, j0 - r):j0 + r, max(0, i0 - r):i0 + r]
            if not win.any():
                continue
            jj, ii = np.nonzero(win)
            k = np.argmin((jj - min(r, j0)) ** 2 + (ii - min(r, i0)) ** 2)
            pts.append((minX + (max(0, i0 - r) + ii[k]) * step, minY + (max(0, j0 - r) + jj[k]) * step))
    wp = np.asarray(pts, dtype=np.float32)
    N = len(wp)

    rows, cols, w = [], [], []
    for a in range(N):
        d = np.hypot(*(wp - wp[a]).T)
        for b in np.nonzero((d > 0) & (d <= link))[0]:
            if b > a and straight_clear(clear, minX, minY, step, wp[a], wp[b]):
                rows += [a, b]; cols += [b, a]; w += [d[b], d[b]]
    G = csr_matrix((w, (rows, cols)), shape=(N, N))
    dist, pred = shortest_path(G, directed=False, return_predecessors=True)
    # nxt[g, s]: step from s toward g. On an undirected graph, the predecessor of s on the path from g is it.
    nxt = pred.astype(np.int16)
    nxt[pred < 0] = -1

    # Cell -> nearest waypoint with a straight clear line (4 m cells).
    cs = 4
    cellwp = np.full((ny // cs + 1, nx // cs + 1), -1, dtype=np.int16)
    for cj in range(cellwp.shape[0]):
        for ci in range(cellwp.shape[1]):
            x, y = minX + ci * cs * step, minY + cj * cs * step
            i, j = min(nx - 1, ci * cs), min(ny - 1, cj * cs)
            if not clear[j, i]:
                continue
            d = np.hypot(wp[:, 0] - x, wp[:, 1] - y)
            for k in np.argsort(d)[:6]:
                if d[k] > link * 1.5:
                    break
                if straight_clear(clear, minX, minY, step, (x, y), wp[k]):
                    cellwp[cj, ci] = k
                    break

    comp = np.isfinite(dist[0]).sum()
    np.savez_compressed(out, wp=wp, dist=dist.astype(np.float32), nxt=nxt, cellwp=cellwp,
                        meta=np.array([minX, minY, step, cs], dtype=np.float64))
    print(f"waypoints {N}, edges {len(w)//2}, reachable from wp0 {comp}/{N}, "
          f"cells mapped {(cellwp >= 0).mean():.3f}")


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0], a[1], *(float(v) for v in a[2:]))
