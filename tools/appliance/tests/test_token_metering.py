"""Unit tests for the ComputeMesh Provider Node Token Metering module."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.appliance.token_metering import (
    PROVIDER_USD_PER_MILLION_TOKENS,
    TokenStats,
    get_token_stats,
    load_token_stats,
    record_tokens,
    save_token_stats,
    sync_with_coordinator,
)


class TestTokenMetering(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.storage_file = Path(self.tmp_dir.name) / "token_accounting.json"
        self.patcher = patch("tools.appliance.token_metering._get_token_storage_path", return_value=self.storage_file)
        self.patcher.start()
        import tools.appliance.token_metering as tm
        tm._CACHED_STATS = None
        tm._DIRTY = False

    def tearDown(self) -> None:
        self.patcher.stop()
        import tools.appliance.token_metering as tm
        tm._CACHED_STATS = None
        tm._DIRTY = False
        self.tmp_dir.cleanup()

    def test_default_empty_stats(self) -> None:
        stats = load_token_stats()
        self.assertEqual(stats.total_tokens_served, 0)
        self.assertEqual(stats.total_earnings_usd, 0.0)
        self.assertEqual(stats.prompt_tokens, 0)
        self.assertEqual(stats.completion_tokens, 0)

    def test_record_tokens_increments_and_computes_earnings(self) -> None:
        st = record_tokens(prompt_tokens=150, completion_tokens=350)
        self.assertEqual(st.total_tokens_served, 500)
        self.assertEqual(st.prompt_tokens, 150)
        self.assertEqual(st.completion_tokens, 350)
        expected_earn = round(500 * (PROVIDER_USD_PER_MILLION_TOKENS / 1_000_000.0), 6)
        self.assertEqual(st.total_earnings_usd, expected_earn)

        # Check persistence
        loaded = load_token_stats()
        self.assertEqual(loaded.total_tokens_served, 500)
        self.assertEqual(loaded.total_earnings_usd, expected_earn)

    def test_sync_with_coordinator_takes_max(self) -> None:
        record_tokens(100, 100)  # total 200
        st = sync_with_coordinator(coordinator_tokens=1000, coordinator_earnings_usd=0.00075)
        self.assertEqual(st.total_tokens_served, 1000)
        self.assertEqual(st.total_earnings_usd, 0.00075)

        # If coordinator sends lower, local is preserved
        st2 = sync_with_coordinator(coordinator_tokens=500, coordinator_earnings_usd=0.0001)
        self.assertEqual(st2.total_tokens_served, 1000)
        self.assertEqual(st2.total_earnings_usd, 0.00075)

    def test_get_token_stats_dict(self) -> None:
        record_tokens(50, 50)
        d = get_token_stats()
        self.assertEqual(d["tokens_processed"], 100)
        self.assertEqual(d["earnings_cm"], 100)
        self.assertGreater(d["earnings_usd"], 0.0)


if __name__ == "__main__":
    unittest.main()
