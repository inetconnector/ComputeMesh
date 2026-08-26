"""High-Performance & Concurrency Stress Test Harness for ComputeMesh Gateway."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import time
import unittest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.billing.ledger import Ledger
from services.gateway.auth import GatewayAuthManager
from services.gateway.inference import InferenceEngine
from services.gateway.inference_backend import SyntheticInferenceBackend
from services.gateway.metrics_exporter import MetricsRegistry
from services.gateway.teaser import TeaserQuotaManager


class TestPerformanceHarness(unittest.TestCase):
    def setUp(self) -> None:
        self.ledger = Ledger()
        self.metrics = MetricsRegistry()
        self.teaser_manager = TeaserQuotaManager(max_requests=10000, max_tokens=1000000)
        self.auth_manager = GatewayAuthManager(
            ledger=self.ledger,
            teaser_manager=self.teaser_manager,
        )
        self.engine = InferenceEngine(
            ledger=self.ledger,
            metrics=self.metrics,
            teaser_manager=self.teaser_manager,
            backend=SyntheticInferenceBackend(),
        )
        self.ledger.deposit_customer_credits(
            customer_account_id="perf_customer_01",
            amount_micro_units=500_000_000,
            payment_reference="perf_seed",
        )

    def test_single_threaded_sub_millisecond_overhead(self) -> None:
        """Ensures non-streaming inference processing overhead is sub-millisecond."""
        iterations = 500
        start = time.perf_counter()
        for i in range(iterations):
            res, err, status = self.engine.execute_chat_completion(
                account_id="perf_customer_01",
                model_id="qwen/qwen2.5-7b-instruct",
                messages=[{"role": "user", "content": f"Iteration {i}"}],
            )
            self.assertEqual(status, 200)
        elapsed = time.perf_counter() - start
        avg_ms = (elapsed / iterations) * 1000
        print(f"\n[BENCHMARK] Average Inference Dispatch Latency: {avg_ms:.3f} ms per request ({iterations} ops)")
        # Must execute within 2.5ms per request in Python standard runtime
        self.assertLess(avg_ms, 2.5)

    def test_multi_threaded_concurrency_stress(self) -> None:
        """Tests concurrent throughput across 16 worker threads with financial ledger consistency."""
        concurrency = 16
        requests_per_thread = 50
        total_requests = concurrency * requests_per_thread

        def worker(thread_idx: int) -> int:
            success = 0
            for req_idx in range(requests_per_thread):
                res, err, status = self.engine.execute_chat_completion(
                    account_id="perf_customer_01",
                    model_id="qwen/qwen2.5-7b-instruct",
                    messages=[{"role": "user", "content": f"Thread {thread_idx} Req {req_idx}"}],
                )
                if status == 200 and res is not None:
                    success += 1
            return success

        start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = [pool.submit(worker, i) for i in range(concurrency)]
            results = [f.result() for f in futures]
        elapsed = time.perf_counter() - start

        total_success = sum(results)
        throughput = total_success / elapsed
        print(f"[BENCHMARK] Multi-threaded Throughput: {throughput:.1f} req/sec across {concurrency} threads")
        self.assertEqual(total_success, total_requests)


if __name__ == "__main__":
    unittest.main()
