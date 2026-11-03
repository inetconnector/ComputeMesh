"""The untrusted HTTP crawler must bound gzip expansion before allocating it."""

import gzip

import pytest

from services.concert_research.crawler import _decompress_gzip_with_limit


def test_valid_gzip_response_round_trips() -> None:
    original = b"hello world" * 75
    assert _decompress_gzip_with_limit(gzip.compress(original), len(original)) == original


@pytest.mark.parametrize("size", [0, 1, 100, 4096])
def test_gzip_decompression_rejects_response_over_limit(size: int) -> None:
    huge = b"x" * 2_000_000
    compressed = gzip.compress(huge)
    assert len(compressed) < 5000
    with pytest.raises(ValueError, match="decompressed response exceeds"):
        _decompress_gzip_with_limit(compressed, size)


def test_gzip_decompression_accepts_exact_boundary() -> None:
    payload = b"1234567890"
    assert _decompress_gzip_with_limit(gzip.compress(payload), 10) == payload


def test_invalid_gzip_is_not_silently_accepted() -> None:
    with pytest.raises((gzip.BadGzipFile, EOFError, OSError)):
        _decompress_gzip_with_limit(b"not compressed content", 1024)


def test_negative_response_limit_is_rejected() -> None:
    with pytest.raises(ValueError, match="negative maximum"):
        _decompress_gzip_with_limit(gzip.compress(b"a"), -1)
