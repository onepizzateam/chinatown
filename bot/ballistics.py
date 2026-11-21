"""Closed-form aiming: gun intercept and mortar arcs (no allocation, pure math).

Conventions (protocol.md section 5): x east, y north, z up; yaw from +x counter-clockwise;
pitch up-positive. Shots leave `radius + 0.5` m out from the muzzle; for the mortar the
offset is horizontal only (verified on the public replay), and we assume the same for the gun.
Bullets do not inherit the shooter's velocity (assumption; checked later against the sim).
"""
from math import atan2, cos, hypot, sin, sqrt, tan, atan, isfinite


def shot_origin(pos, yaw, muzzle_h, radius):
    off = radius + 0.5
    return (pos[0] + off * cos(yaw), pos[1] + off * sin(yaw), pos[2] + muzzle_h)


def intercept_time(rel, vel, speed):
    """Smallest t > 0 with |rel + vel t| = speed t, or None. rel/vel are 3-tuples."""
    a = vel[0] ** 2 + vel[1] ** 2 + vel[2] ** 2 - speed * speed
    b = 2 * (rel[0] * vel[0] + rel[1] * vel[1] + rel[2] * vel[2])
    c = rel[0] ** 2 + rel[1] ** 2 + rel[2] ** 2
    if abs(a) < 1e-9:
        return (-c / b) if b < 0 else None
    disc = b * b - 4 * a * c
    if disc < 0:
        return None
    r = sqrt(disc)
    ts = [t for t in ((-b - r) / (2 * a), (-b + r) / (2 * a)) if t > 0]
    return min(ts) if ts else None


def gun_aim(shooter_pos, shooter_yaw, muzzle_h, radius, target_pos, target_vel, target_center_h, speed, iters=3):
    """Return (yaw, pitch, flight_time) that leads a target moving at constant velocity.

    The shot origin depends on the yaw, so iterate: aim, recompute origin, re-solve.
    """
    yaw = shooter_yaw
    tx, ty, tz = target_pos[0], target_pos[1], target_pos[2] + target_center_h
    t = None
    for _ in range(iters):
        ox, oy, oz = shot_origin(shooter_pos, yaw, muzzle_h, radius)
        t = intercept_time((tx - ox, ty - oy, tz - oz), target_vel, speed)
        if t is None:
            t = hypot(tx - ox, ty - oy) / speed
        px, py, pz = tx + target_vel[0] * t, ty + target_vel[1] * t, tz + target_vel[2] * t
        yaw = atan2(py - oy, px - ox)
        pitch = atan2(pz - oz, hypot(px - ox, py - oy))
    return yaw, pitch, t


def mortar_pitch(d, h, v, g, high=False):
    """Pitch that lands a shell at horizontal distance d and height difference h (target - origin).

    Solves h = d tan(p) - g d^2 / (2 v^2 cos^2 p). Returns None when out of range.
    `high` picks the lob (to clear buildings); otherwise the flatter, faster arc.
    """
    if d < 1e-6:
        return None
    v2 = v * v
    disc = v2 * v2 - g * (g * d * d + 2 * h * v2)
    if disc < 0:
        return None
    r = sqrt(disc)
    p = atan((v2 + r) / (g * d)) if high else atan((v2 - r) / (g * d))
    return p if isfinite(p) else None


def mortar_aim(shooter_pos, shooter_yaw, mortar_h, radius, target_pos, target_vel, v, g, high=False, iters=4):
    """Return (yaw, pitch, flight_time) for a mortar shell, leading the target's ground motion."""
    yaw = shooter_yaw
    tx, ty, tz = target_pos
    t = 0.0
    p = None
    for _ in range(iters):
        ox, oy, oz = shot_origin(shooter_pos, yaw, mortar_h, radius)
        px, py = tx + target_vel[0] * t, ty + target_vel[1] * t
        d = hypot(px - ox, py - oy)
        p = mortar_pitch(d, tz - oz, v, g, high)
        if p is None:
            return None
        yaw = atan2(py - oy, px - ox)
        t = d / (v * cos(p))
    return yaw, p, t


def wrap(a):
    """Wrap an angle to [-pi, pi)."""
    from math import pi
    return (a + pi) % (2 * pi) - pi


def aim_error_ok(cur_yaw, cur_pitch, want_yaw, want_pitch, dist, target_radius):
    """True when the current torso aim would pass within the target's radius at this distance."""
    lateral = abs(wrap(cur_yaw - want_yaw)) * dist
    vertical = abs(cur_pitch - want_pitch) * dist
    return lateral < target_radius * 0.8 and vertical < 3.0
