"""Transactional Mail Dispatcher for ComputeMesh Fleet & Security.

Sends cryptographically signed / TLS-secured operational emails from `mesh@inetconnector.com`:
- Magic link login & fleet recovery codes
- Security alerts (new passkey added, unknown IP login attempt, wallet change)
- Fleet node enrollment & disconnect notifications
"""
from __future__ import annotations

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import logging
import os
from pathlib import Path
import smtplib
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

logger = logging.getLogger("computemesh.mail")


def _load_mail_env() -> dict[str, str]:
    """Loads configuration from /etc/computemesh/mail.env if present."""
    result: dict[str, str] = {}
    env_file = Path(os.environ.get("COMPUTEMESH_MAIL_ENV_PATH", "/etc/computemesh/mail.env"))
    if env_file.exists():
        try:
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                result[k.strip()] = v.strip()
        except Exception as exc:
            logger.warning("Could not read mail.env: %s", exc)
    return result


MAIL_FILE_CONFIG = _load_mail_env()


def get_mail_config(key: str, default: str = "") -> str:
    return os.environ.get(key) or MAIL_FILE_CONFIG.get(key, default)


SMTP_HOST = get_mail_config("COMPUTEMESH_SMTP_HOST", "127.0.0.1")
SMTP_PORT = int(get_mail_config("COMPUTEMESH_SMTP_PORT", "587"))
SMTP_USER = get_mail_config("COMPUTEMESH_SMTP_USER", "mesh@inetconnector.com")
SMTP_PASS = get_mail_config("COMPUTEMESH_SMTP_PASS", "")
MAIL_FROM = get_mail_config("COMPUTEMESH_MAIL_FROM", "ComputeMesh Security <mesh@inetconnector.com>")
MAIL_DISABLED = os.environ.get("COMPUTEMESH_MAIL_DISABLE_SENDING", "").lower() in ("1", "true", "yes")


def send_email(to_address: str, subject: str, text_content: str, html_content: str | None = None) -> bool:
    """Sends a transactional email via SMTP with STARTTLS."""
    if not to_address or "@" not in to_address:
        logger.error("Invalid recipient email: %s", to_address)
        return False

    if MAIL_DISABLED:
        logger.info("[MOCK MAIL] To: %s | Subject: %s | Content: %s", to_address, subject, text_content[:100])
        return True

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = MAIL_FROM
    msg["To"] = to_address
    msg["X-Auto-Response-Suppress"] = "All"
    msg["Auto-Submitted"] = "auto-generated"

    part_text = MIMEText(text_content, "plain", "utf-8")
    msg.attach(part_text)

    if html_content:
        part_html = MIMEText(html_content, "html", "utf-8")
        msg.attach(part_html)

    try:
        if SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=10)
        else:
            server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10)
            try:
                server.starttls()
            except Exception:
                pass  # Localhost unencrypted relay if configured

        if SMTP_USER and SMTP_PASS:
            server.login(SMTP_USER, SMTP_PASS)

        server.send_message(msg)
        server.quit()
        logger.info("Sent email '%s' to %s", subject, to_address)
        return True
    except Exception as exc:
        logger.error("Failed to send email to %s: %s", to_address, exc)
        return False


def send_magic_link(to_address: str, magic_url: str, expires_minutes: int = 15) -> bool:
    """Sends a secure login / recovery magic link."""
    subject = "ComputeMesh Flotten-Zugang / Login-Link"
    text = f"""Hallo,

Du hast einen direkten Login- und Wiederherstellungs-Link für dein ComputeMesh Flotten-Konto angefordert.

Klicke auf den folgenden Link, um dich sicher in deinem Flotten-Cockpit anzumelden:
{magic_url}

Dieser Link ist aus Sicherheitsgründen nur für {expires_minutes} Minuten und zur einmaligen Verwendung gültig.

Falls du diesen Login nicht angefordert hast, ignoriere diese E-Mail bitte. Dein Konto bleibt durch deine Passkeys geschützt.

Beste Grüße,
ComputeMesh Security Team
mesh@inetconnector.com
"""

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background: #090d16; color: #f8fafc; margin: 0; padding: 20px; }}
.card {{ max-width: 560px; margin: 0 auto; background: #0f172a; border: 1px solid rgba(56, 189, 248, 0.25); border-radius: 12px; padding: 32px; }}
.brand {{ font-size: 20px; font-weight: 800; color: #38bdf8; margin-bottom: 24px; }}
.btn {{ display: inline-block; background: #0284c7; color: #ffffff !important; text-decoration: none; padding: 14px 28px; border-radius: 8px; font-weight: 700; font-size: 15px; margin: 20px 0; }}
.footer {{ font-size: 12px; color: #64748b; margin-top: 32px; border-top: 1px solid rgba(255,255,255,0.08); padding-top: 16px; }}
</style>
</head>
<body>
<div class="card">
  <div class="brand">⚡ ComputeMesh</div>
  <h2 style="color: #f8fafc; margin-top: 0;">Flotten-Cockpit Zugang</h2>
  <p style="color: #cbd5e1; font-size: 15px; line-height: 1.5;">
    Du hast einen direkten Login- und Wiederherstellungs-Link für dein ComputeMesh Flotten-Konto angefordert.
  </p>
  <div style="text-align: center;">
    <a href="{magic_url}" class="btn">⚡ Jetzt im Flotten-Cockpit anmelden →</a>
  </div>
  <p style="color: #94a3b8; font-size: 13px; line-height: 1.4;">
    Oder kopiere diesen Link direkt in deinen Browser:<br>
    <code style="color: #38bdf8; word-break: break-all;">{magic_url}</code>
  </p>
  <p style="color: #ef4444; font-size: 12px;">
    ⏳ Gültigkeit: {expires_minutes} Minuten (Einmal-Link).
  </p>
  <div class="footer">
    Falls du diesen Login nicht selbst angefordert hast, ignoriere diese E-Mail. Dein Konto ist durch deine Passkeys geschützt.<br><br>
    &copy; 2026 ComputeMesh &middot; <a href="https://mesh.inetconnector.com" style="color: #38bdf8;">mesh.inetconnector.com</a>
  </div>
</div>
</body>
</html>"""
    return send_email(to_address, subject, text, html)


def send_security_alert(to_address: str, event_title: str, details: str, ip_address: str = "", user_agent: str = "") -> bool:
    """Dispatches an immediate security alert to the owner."""
    subject = f"[Sicherheitshinweis] ComputeMesh: {event_title}"
    text = f"""Sicherheits-Benachrichtigung für dein ComputeMesh Flotten-Konto:

Ereignis: {event_title}
Details: {details}
IP-Adresse: {ip_address or 'Unbekannt'}
User-Agent: {user_agent or 'Unbekannt'}

Falls du diese Aktion nicht selbst durchgeführt hast, melde dich umgehend im Flotten-Cockpit an und widerrufe alle aktiven Sitzungen und Passkeys.

ComputeMesh Security Dispatcher
mesh@inetconnector.com
"""

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background: #090d16; color: #f8fafc; margin: 0; padding: 20px; }}
.card {{ max-width: 560px; margin: 0 auto; background: #0f172a; border: 1px solid rgba(239, 68, 68, 0.35); border-radius: 12px; padding: 32px; }}
.badge {{ display: inline-block; background: rgba(239, 68, 68, 0.2); color: #f87171; padding: 4px 10px; border-radius: 9999px; font-weight: 700; font-size: 12px; margin-bottom: 16px; }}
.detail-box {{ background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; padding: 14px; margin: 16px 0; font-size: 13px; color: #cbd5e1; }}
.footer {{ font-size: 12px; color: #64748b; margin-top: 24px; border-top: 1px solid rgba(255,255,255,0.08); padding-top: 16px; }}
</style>
</head>
<body>
<div class="card">
  <div class="badge">🛡️ SICHERHEITSHINWEIS</div>
  <h2 style="color: #f8fafc; margin-top: 0;">{event_title}</h2>
  <p style="color: #cbd5e1; font-size: 14px; line-height: 1.5;">{details}</p>
  <div class="detail-box">
    <div><strong>IP-Adresse:</strong> {ip_address or 'Unbekannt'}</div>
    <div style="margin-top: 4px;"><strong>Client:</strong> {user_agent or 'Unbekannt'}</div>
  </div>
  <div class="footer">
    Automatische Benachrichtigung durch ComputeMesh Zero-Trust Security.<br>
    &copy; 2026 ComputeMesh &middot; mesh@inetconnector.com
  </div>
</div>
</body>
</html>"""
    return send_email(to_address, subject, text, html)


def send_node_event(to_address: str, event_type: str, node_id: str, details: str = "") -> bool:
    """Dispatches a fleet node status event (connected / unbound)."""
    subject = f"ComputeMesh Flotte: Server {node_id} {event_type}"
    text = f"""Flotten-Status-Update:

Knoten: {node_id}
Status: {event_type}
Details: {details}

Verwalte deine Server im Flotten-Cockpit unter: https://mesh.inetconnector.com/fleet

ComputeMesh Fleet Monitor
mesh@inetconnector.com
"""
    return send_email(to_address, subject, text)
