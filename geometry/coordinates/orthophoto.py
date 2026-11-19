"""Uploaded-orthophoto georeferencing against canonical local XY metres."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence

from .core import LocalCoordinateSystem, LocalPoint
from .measurement import SegmentMeasurement, measure_local_segment


@dataclass(frozen=True)
class OrthophotoControlPoint:
    """One image-pixel to canonical-local control point."""

    pixel_x: float
    pixel_y: float
    local_x_m: float
    local_y_m: float


@dataclass(frozen=True)
class AffineTransform2D:
    """Six-parameter affine transform.

    x_m = a * pixel_x + b * pixel_y + c
    y_m = d * pixel_x + e * pixel_y + f
    """

    a: float
    b: float
    c: float
    d: float
    e: float
    f: float

    def pixel_to_local(self, pixel_x: float, pixel_y: float) -> LocalPoint:
        x = self.a * pixel_x + self.b * pixel_y + self.c
        y = self.d * pixel_x + self.e * pixel_y + self.f
        return LocalPoint(x, y, 0.0)

    def local_to_pixel(
        self,
        local_x_m: float,
        local_y_m: float,
    ) -> tuple[float, float]:
        determinant = self.a * self.e - self.b * self.d
        if abs(determinant) < 1e-15:
            raise ValueError("affine transform is singular")
        x = local_x_m - self.c
        y = local_y_m - self.f
        pixel_x = (self.e * x - self.b * y) / determinant
        pixel_y = (-self.d * x + self.a * y) / determinant
        return pixel_x, pixel_y


@dataclass(frozen=True)
class OrthophotoCalibration:
    transform: AffineTransform2D
    control_point_count: int
    rms_error_m: float


def _solve_3x3(
    matrix: list[list[float]],
    vector: list[float],
) -> tuple[float, float, float]:
    augmented = [
        [float(matrix[row][col]) for col in range(3)] + [float(vector[row])]
        for row in range(3)
    ]
    for pivot in range(3):
        best = max(
            range(pivot, 3),
            key=lambda row: abs(augmented[row][pivot]),
        )
        if abs(augmented[best][pivot]) < 1e-15:
            raise ValueError("orthophoto control points are degenerate")
        if best != pivot:
            augmented[pivot], augmented[best] = (
                augmented[best],
                augmented[pivot],
            )

        divisor = augmented[pivot][pivot]
        augmented[pivot] = [value / divisor for value in augmented[pivot]]

        for row in range(3):
            if row == pivot:
                continue
            factor = augmented[row][pivot]
            augmented[row] = [
                augmented[row][col] - factor * augmented[pivot][col]
                for col in range(4)
            ]

    return (
        augmented[0][3],
        augmented[1][3],
        augmented[2][3],
    )


def fit_affine_control_points(
    control_points: Sequence[OrthophotoControlPoint],
) -> OrthophotoCalibration:
    """Least-squares affine calibration from at least three control points."""
    if len(control_points) < 3:
        raise ValueError("at least three orthophoto control points are required")

    normal = [[0.0] * 3 for _ in range(3)]
    target_x = [0.0, 0.0, 0.0]
    target_y = [0.0, 0.0, 0.0]

    for point in control_points:
        row = [float(point.pixel_x), float(point.pixel_y), 1.0]
        for i in range(3):
            target_x[i] += row[i] * float(point.local_x_m)
            target_y[i] += row[i] * float(point.local_y_m)
            for j in range(3):
                normal[i][j] += row[i] * row[j]

    a, b, c = _solve_3x3(normal, target_x)
    d, e, f = _solve_3x3(normal, target_y)
    transform = AffineTransform2D(a, b, c, d, e, f)

    squared_error = 0.0
    for point in control_points:
        resolved = transform.pixel_to_local(point.pixel_x, point.pixel_y)
        squared_error += (
            (resolved.x_m - point.local_x_m) ** 2
            + (resolved.y_m - point.local_y_m) ** 2
        )
    rms = math.sqrt(squared_error / len(control_points))

    return OrthophotoCalibration(
        transform=transform,
        control_point_count=len(control_points),
        rms_error_m=rms,
    )


def measure_orthophoto_segment(
    start_pixel: tuple[float, float],
    end_pixel: tuple[float, float],
    calibration: OrthophotoCalibration,
    coordinate_system: LocalCoordinateSystem,
) -> SegmentMeasurement:
    """Measure orthophoto pixels only after calibration into local metres."""
    start = calibration.transform.pixel_to_local(*start_pixel)
    end = calibration.transform.pixel_to_local(*end_pixel)
    return measure_local_segment(start, end, coordinate_system)
