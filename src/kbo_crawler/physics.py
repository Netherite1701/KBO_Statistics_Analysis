"""Small PTS geometry helpers.

Naver's ``crossPlateY`` is the front edge's Y coordinate, not pitch height.
The actual height is reconstructed from the recorded release position,
velocity, and acceleration instead of assuming a fixed release height.
"""

from __future__ import annotations

import math


def plate_crossing_height(
    *,
    y0: float | int | None,
    z0: float | int | None,
    vy0: float | int | None,
    vz0: float | int | None,
    ay: float | int | None,
    az: float | int | None,
    plate_y: float | int | None,
) -> float | None:
    values = (y0, z0, vy0, vz0, ay, az, plate_y)
    if any(value is None for value in values):
        return None
    y_start, z_start, vy, vz, accel_y, accel_z, target_y = map(float, values)

    c = y_start - target_y
    if abs(accel_y) < 1e-12:
        if abs(vy) < 1e-12:
            return None
        roots = (-c / vy,)
    else:
        discriminant = vy * vy - 2.0 * accel_y * c
        if discriminant < 0:
            return None
        root = math.sqrt(discriminant)
        roots = ((-vy - root) / accel_y, (-vy + root) / accel_y)

    valid = [time for time in roots if math.isfinite(time) and time >= 0]
    if not valid:
        return None
    time = min(valid)
    height = z_start + vz * time + 0.5 * accel_z * time * time
    return height if math.isfinite(height) else None
