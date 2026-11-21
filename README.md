# chinatown: Mech Royale bot (onepizzateam)

An entry for the Builders Buildathon Mech Royale track: a Python bot that speaks `mechfight/1` on stdin and stdout.

## Layout

| Path | What it is |
| --- | --- |
| `bot/main.py` | Decision loop: target choice, movement, weapons, looting, upgrades, zone, free-for-all detection |
| `bot/ballistics.py` | Closed-form gun intercept and mortar arcs |
| `bot/world.py` | Baked arena rasters and line-of-sight queries |
| `bot/nav.py` | Ground navigation over a precomputed waypoint routing table |
| `bot/mechfight.py` | The organisers' protocol wrapper from the kit, unchanged |
| `bot/data/map.npz` | Arena rasters baked by `tools/bake_map.py` from the kit's `arena/v2` |
| `tools/bake_nav.py` | Builds the routing table during `docker build`, so it is not checked in |

## Build and check

```sh
docker build -t chinatown .
python3 check/check.py --map-dir /arena -- docker run --rm -i --network none --cpus 1 --memory 512m \
  --read-only --tmpfs /tmp:rw,size=64m --user 65534:65534 -v "$PWD/arena:/arena:ro" chinatown
```

To rebuild the map rasters from the kit: `python tools/bake_map.py <kit>/arena bot/data/map.npz`.
