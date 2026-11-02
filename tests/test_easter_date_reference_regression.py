"""Easter Sunday reference dates remain stable across refactors."""

from datetime import date

import pytest

from services.mcp.builtin.time_calendar import calculate_easter_sunday


@pytest.mark.parametrize(
    ("year", "expected"),
    [(2024, date(2024, 3, 31)), (2025, date(2025, 4, 20)), (2026, date(2026, 4, 5))],
)
def test_known_easter_sundays(year: int, expected: date) -> None:
    assert calculate_easter_sunday(year) == expected
