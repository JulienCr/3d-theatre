"""3-vector helpers shared by the rig and the barn doors: plain `(x, y, z)` tuples."""

from __future__ import annotations

import math

Vec = tuple[float, float, float]


def sub(a, b) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def add(a, b) -> Vec:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def mul(a, k: float) -> Vec:
    return (a[0] * k, a[1] * k, a[2] * k)


def dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def unit(a) -> Vec:
    n = math.sqrt(dot(a, a))
    return (a[0] / n, a[1] / n, a[2] / n)


def angle_between(a, b) -> float:
    """Angle in degrees between two non-zero vectors."""
    return math.degrees(math.acos(min(max(dot(unit(a), unit(b)), -1.0), 1.0)))
