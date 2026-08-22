"""Unit tests for Web3 & On-Chain Crypto Payment Ingestion Engine."""
import unittest

from services.billing.crypto_payments import (
    CryptoPaymentError,
    CryptoPaymentService,
)
from services.billing.ledger import Ledger


class TestCryptoPayments(unittest.TestCase):
    def setUp(self) -> None:
        self.ledger = Ledger()
        self.crypto_svc = CryptoPaymentService(ledger=self.ledger)

    def test_deposit_address_deterministic(self) -> None:
        addr1 = self.crypto_svc.register_customer_deposit_address("cust_web3_01", "arbitrum")
        addr2 = self.crypto_svc.register_customer_deposit_address("cust_web3_01", "arbitrum")
        self.assertTrue(addr1.startswith("0x"))
        self.assertEqual(len(addr1), 42)
        self.assertEqual(addr1, addr2)

    def test_usdt_arbitrum_successful_deposit(self) -> None:
        deposit_addr = self.crypto_svc.register_customer_deposit_address("cust_web3_02", "arbitrum")
        # 100 USDT = 100 * 10^6 base units
        res = self.crypto_svc.process_confirmed_transaction(
            tx_hash="0xabcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
            network="arbitrum",
            token="USDT",
            from_address="0x1111111111111111111111111111111111111111",
            to_address=deposit_addr,
            amount_raw=100_000_000,
        )
        self.assertEqual(res["status"], "credited")
        self.assertEqual(res["amount_usd"], 100.00)
        self.assertEqual(self.ledger.get_balance("cust_web3_02"), 100_000_000)

    def test_duplicate_tx_hash_is_idempotent(self) -> None:
        deposit_addr = self.crypto_svc.register_customer_deposit_address("cust_web3_03", "polygon")
        tx_hash = "0x9999888877776666555544443333222211110000aaaaabbbbbcccccdddddeeeee"

        res1 = self.crypto_svc.process_confirmed_transaction(
            tx_hash=tx_hash,
            network="polygon",
            token="USDC",
            from_address="0x2222222222222222222222222222222222222222",
            to_address=deposit_addr,
            amount_raw=50_000_000,
        )
        self.assertEqual(res1["status"], "credited")
        self.assertEqual(self.ledger.get_balance("cust_web3_03"), 50_000_000)

        # Duplicate replay
        res2 = self.crypto_svc.process_confirmed_transaction(
            tx_hash=tx_hash,
            network="polygon",
            token="USDC",
            from_address="0x2222222222222222222222222222222222222222",
            to_address=deposit_addr,
            amount_raw=50_000_000,
        )
        self.assertEqual(res2["status"], "already_processed")
        self.assertEqual(self.ledger.get_balance("cust_web3_03"), 50_000_000)

    def test_unsupported_network_rejected(self) -> None:
        with self.assertRaises(CryptoPaymentError):
            self.crypto_svc.register_customer_deposit_address("cust_fail", "solana")

    def test_sub_minimum_deposit_rejected(self) -> None:
        deposit_addr = self.crypto_svc.register_customer_deposit_address("cust_min", "arbitrum")
        with self.assertRaises(CryptoPaymentError):
            self.crypto_svc.process_confirmed_transaction(
                tx_hash="0x123",
                network="arbitrum",
                token="USDT",
                from_address="0x111",
                to_address=deposit_addr,
                amount_raw=2_000_000,  # $2.00 (below $5.00 min)
            )


if __name__ == "__main__":
    unittest.main()
