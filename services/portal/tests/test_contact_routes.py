"""Unit tests for portal contact form endpoint and mail dispatcher integration."""
from __future__ import annotations

import json
from unittest.mock import patch
import unittest
import urllib.request
import urllib.error

from services.portal.server import PortalHandler
from services.portal import mail_dispatcher


class TestPortalContactRoutes(unittest.TestCase):
    """Verifies POST /api/v1/contact handling and email delivery to mesh@inetconnector.com."""

    def test_send_contact_inquiry_formats_email_correctly(self) -> None:
        with patch.object(mail_dispatcher, "send_email", return_value=True) as mock_send:
            ok = mail_dispatcher.send_contact_inquiry(
                from_name="Frederik Tech",
                from_email="frede@inetconnector.com",
                topic="developer",
                message="We would like to integrate 10x RTX 4090 nodes.",
                ip_address="192.168.1.100",
                user_agent="Mozilla/5.0 TestBrowser",
            )
            self.assertTrue(ok)
            self.assertTrue(mock_send.called)
            args, kwargs = mock_send.call_args
            to_addr, subject, text, html = args
            self.assertEqual(to_addr, "mesh@inetconnector.com")
            self.assertIn("Frederik Tech", subject)
            self.assertIn("Entwickler-API", subject)
            self.assertIn("frede@inetconnector.com", text)
            self.assertIn("10x RTX 4090", text)
            self.assertEqual(kwargs.get("reply_to"), "frede@inetconnector.com")

    def test_send_email_respects_reply_to_header(self) -> None:
        with patch("smtplib.SMTP") as mock_smtp:
            instance = mock_smtp.return_value
            ok = mail_dispatcher.send_email(
                to_address="mesh@inetconnector.com",
                subject="Test Subject",
                text_content="Test Body",
                reply_to="customer@example.org",
            )
            self.assertTrue(ok)
            self.assertTrue(instance.send_message.called)
            sent_msg = instance.send_message.call_args[0][0]
            self.assertEqual(sent_msg["Reply-To"], "customer@example.org")
            self.assertEqual(sent_msg["To"], "mesh@inetconnector.com")


if __name__ == "__main__":
    unittest.main()
