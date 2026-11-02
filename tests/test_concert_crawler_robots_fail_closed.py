"""Unavailable robots.txt must not silently grant crawl permission."""

from contextlib import nullcontext
from unittest.mock import Mock, patch
from urllib import error

import pytest

from services.concert_research.config import ConcertResearchConfig
from services.concert_research.crawler import SafeFetcher


@pytest.fixture
def fetcher() -> SafeFetcher:
    return SafeFetcher(ConcertResearchConfig.from_env())


@pytest.mark.parametrize("failure", [
    error.HTTPError("https://concert.example/robots.txt", 403, "forbidden", {}, None),
    error.HTTPError("https://concert.example/robots.txt", 429, "rate limited", {}, None),
    error.HTTPError("https://concert.example/robots.txt", 503, "unavailable", {}, None),
    error.URLError("dns timeout"),
    TimeoutError("connection timeout"),
    OSError("connection reset"),
])
def test_robots_network_error_is_denied(fetcher: SafeFetcher, failure: Exception) -> None:
    with (
        patch("services.concert_research.crawler.validate_public_http_url", side_effect=lambda url: url),
        patch("services.concert_research.crawler.request.urlopen", side_effect=failure),
    ):
        with pytest.raises(PermissionError, match="cannot verify robots"):
            fetcher.allowed("https://concert.example/private")
    assert fetcher._robots == {}


@pytest.mark.parametrize("not_found", [404, 410])
def test_confirmed_missing_robots_is_not_an_error(fetcher: SafeFetcher, not_found: int) -> None:
    failure = error.HTTPError(
        "https://concert.example/robots.txt", not_found, "not found", {}, None,
    )
    with (
        patch("services.concert_research.crawler.validate_public_http_url", side_effect=lambda url: url),
        patch("services.concert_research.crawler.request.urlopen", side_effect=failure),
    ):
        assert fetcher.allowed("https://concert.example/agenda") is True


def test_robots_disallow_rule_is_observed(fetcher: SafeFetcher) -> None:
    response = Mock()
    response.geturl.return_value = "https://concert.example/robots.txt"
    response.read.return_value = b"User-agent: *\nDisallow: /private\n"
    with (
        patch("services.concert_research.crawler.validate_public_http_url", side_effect=lambda url: url),
        patch("services.concert_research.crawler.request.urlopen", return_value=nullcontext(response)),
    ):
        assert fetcher.allowed("https://concert.example/private") is False
        assert fetcher.allowed("https://concert.example/agenda") is True
