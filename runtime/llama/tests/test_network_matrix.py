from __future__ import annotations

import pytest

from runtime.llama.network_matrix import MatrixPoint, build_points


def test_build_points_skips_impossible_jitter_combinations() -> None:
    points = build_points((0.0, 5.0, 10.0), (0.0, 2.0, 20.0), seed=100)
    assert points == (
        MatrixPoint(0.0, 0.0, 100),
        MatrixPoint(5.0, 0.0, 101),
        MatrixPoint(5.0, 2.0, 102),
        MatrixPoint(10.0, 0.0, 103),
        MatrixPoint(10.0, 2.0, 104),
    )


def test_matrix_point_rejects_invalid_delay_or_jitter() -> None:
    with pytest.raises(ValueError):
        MatrixPoint(-1.0, 0.0, 1)
    with pytest.raises(ValueError):
        MatrixPoint(5.0, 6.0, 1)


def test_build_points_requires_at_least_one_valid_point() -> None:
    with pytest.raises(ValueError):
        build_points((0.0,), (1.0,), seed=1)
