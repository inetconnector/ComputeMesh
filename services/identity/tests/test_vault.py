#!/usr/bin/env python3
"""Unit tests for AES-256-GCM EncryptedVault."""
import unittest

from services.identity.vault import DEFAULT_VAULT, EncryptedVault, VaultError


class TestEncryptedVault(unittest.TestCase):
    def setUp(self) -> None:
        self.vault = EncryptedVault()

    def test_encrypt_and_decrypt_crypto_wallet(self) -> None:
        wallet = "0x71a99C8D2F8b3A15b81a84511d7e26d0De42B12F"
        encrypted = self.vault.encrypt(wallet)
        self.assertIsNotNone(encrypted)
        self.assertTrue(encrypted.startswith("enc:v1:"))
        self.assertNotIn(wallet, encrypted)

        decrypted = self.vault.decrypt(encrypted)
        self.assertEqual(decrypted, wallet)

    def test_encrypt_and_decrypt_sepa_iban(self) -> None:
        iban = "DE89370400440532013000"
        encrypted = self.vault.encrypt(iban)
        self.assertIsNotNone(encrypted)
        self.assertTrue(encrypted.startswith("enc:v1:"))
        self.assertNotIn(iban, encrypted)

        decrypted = self.vault.decrypt(encrypted)
        self.assertEqual(decrypted, iban)

    def test_tampered_ciphertext_fails_closed(self) -> None:
        encrypted = self.vault.encrypt("secret_value")
        parts = encrypted.split(":")
        # Corrupt ciphertext payload
        corrupted = f"{parts[0]}:{parts[1]}:{parts[2]}:AAAA{parts[3][4:]}"
        with self.assertRaises(VaultError):
            self.vault.decrypt(corrupted)

    def test_mask_sensitive_data(self) -> None:
        wallet = "0x71a99C8D2F8b3A15b81a84511d7e26d0De42B12F"
        masked_wallet = EncryptedVault.mask_sensitive(wallet)
        self.assertEqual(masked_wallet, "0x71a9...B12F")

        iban = "DE89370400440532013000"
        masked_iban = EncryptedVault.mask_sensitive(iban)
        self.assertEqual(masked_iban, "DE89 **** **** **** 3000")

        email = "frede@inetconnector.com"
        masked_email = EncryptedVault.mask_sensitive(email)
        self.assertEqual(masked_email, "f***e@inetconnector.com")


if __name__ == "__main__":
    unittest.main()
