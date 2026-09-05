"""Passkey (WebAuthn) & Zero-Trust Magic-Link Login for Remote Fleet Administration.

A portal account is passwordless: authenticating with FIDO2 passkeys (Face ID / Windows
Hello / Hardware YubiKey) or receiving a single-use cryptographically signed magic link
via `mesh@inetconnector.com`.

Session model: HttpOnly, SameSite=Lax, Secure cookie holding an opaque 256-bit session token.
Audit logging: Every login, failed attempt, passkey change and node unbinding is recorded.
Rate limiting: Token-bucket sliding window to prevent brute-force and email spamming.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from http import HTTPStatus
from http.cookies import SimpleCookie
import logging
import os
from pathlib import Path
import sys
import threading
import time
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import webauthn
from webauthn.helpers import bytes_to_base64url
from webauthn.helpers.exceptions import InvalidRegistrationResponse, InvalidAuthenticationResponse
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from config import CONFIG
from services.portal.fleet_accounts import FleetAccountStore, FleetAccountStoreError
from services.portal.mail_dispatcher import send_magic_link, send_security_alert

logger = logging.getLogger("computemesh.passkey_routes")

SESSION_COOKIE_NAME = "cm_fleet_session"

RP_ID = os.environ.get("COMPUTEMESH_PASSKEY_RP_ID", CONFIG.endpoints.domain)
RP_NAME = "ComputeMesh Fleet"
EXPECTED_ORIGIN = os.environ.get(
    "COMPUTEMESH_PASSKEY_ORIGIN", f"{CONFIG.endpoints.scheme}://{CONFIG.endpoints.domain}"
)


def _resolve_store_path() -> Path:
    raw = os.environ.get("COMPUTEMESH_FLEET_ACCOUNTS_DB_PATH", "").strip()
    if raw:
        return Path(raw)
    return Path("/var/lib/computemesh/fleet_accounts.db")


def _build_store() -> FleetAccountStore:
    try:
        return FleetAccountStore(_resolve_store_path())
    except Exception:
        return FleetAccountStore(Path("/tmp/computemesh_fleet_accounts.db"))


FLEET_ACCOUNT_STORE = _build_store()


class SimpleRateLimiter:
    """In-memory rate limiter per IP / identifier with lock."""

    def __init__(self, max_requests: int = 10, window_seconds: int = 60) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._buckets: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def is_allowed(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            timestamps = self._buckets[key]
            valid_timestamps = [t for t in timestamps if now - t < self.window_seconds]
            if len(valid_timestamps) >= self.max_requests:
                self._buckets[key] = valid_timestamps
                return False
            valid_timestamps.append(now)
            self._buckets[key] = valid_timestamps
            return True


RATE_LIMITER = SimpleRateLimiter(max_requests=10, window_seconds=60)
MAGIC_LINK_RATE_LIMITER = SimpleRateLimiter(max_requests=3, window_seconds=300)


def _client_ip(headers: Any, client_address: tuple[str, int] | None = None) -> str:
    if headers:
        forwarded = str(headers.get("X-Forwarded-For", "")).strip()
        if forwarded:
            return forwarded.split(",")[0].strip()
        real_ip = str(headers.get("X-Real-IP", "")).strip()
        if real_ip:
            return real_ip
    return client_address[0] if client_address else "127.0.0.1"


def _session_cookie_header(token: str, *, clear: bool = False) -> str:
    cookie: SimpleCookie = SimpleCookie()
    cookie[SESSION_COOKIE_NAME] = "" if clear else token
    cookie[SESSION_COOKIE_NAME]["path"] = "/"
    cookie[SESSION_COOKIE_NAME]["httponly"] = True
    cookie[SESSION_COOKIE_NAME]["samesite"] = "Lax"
    if EXPECTED_ORIGIN.startswith("https://"):
        cookie[SESSION_COOKIE_NAME]["secure"] = True
    if clear:
        cookie[SESSION_COOKIE_NAME]["max-age"] = 0
    else:
        cookie[SESSION_COOKIE_NAME]["max-age"] = 30 * 24 * 3600
    return cookie[SESSION_COOKIE_NAME].OutputString()


def session_account_from_headers(headers: Any):
    """Resolves the logged-in FleetAccount (or None) from a request's Cookie header."""
    raw = headers.get("Cookie", "")
    if not raw:
        return None
    cookie: SimpleCookie = SimpleCookie()
    try:
        cookie.load(raw)
    except Exception:
        return None
    morsel = cookie.get(SESSION_COOKIE_NAME)
    if morsel is None:
        return None
    return FLEET_ACCOUNT_STORE.get_session_account(morsel.value)


class PasskeyAuthHandler:
    """Stateless handler methods; each returns (json_body, status, set_cookie_header|None)."""

    def register_begin(self, body: dict[str, Any], headers: Any = None, client_address: tuple[str, int] | None = None) -> tuple[dict[str, Any], HTTPStatus, str | None]:
        ip = _client_ip(headers, client_address)
        if not RATE_LIMITER.is_allowed(f"reg_begin:{ip}"):
            return {"error": "Too many requests. Please try again later."}, HTTPStatus.TOO_MANY_REQUESTS, None

        email = str(body.get("email", "")).strip().lower()
        if not email or "@" not in email:
            return {"error": "a valid email address is required"}, HTTPStatus.BAD_REQUEST, None
        if FLEET_ACCOUNT_STORE.get_account_by_email(email) is not None:
            return (
                {"error": "an account for this email already exists -- sign in instead"},
                HTTPStatus.CONFLICT,
                None,
            )

        options = webauthn.generate_registration_options(
            rp_id=RP_ID,
            rp_name=RP_NAME,
            user_name=email,
            user_display_name=email,
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.PREFERRED,
                user_verification=UserVerificationRequirement.PREFERRED,
            ),
        )
        FLEET_ACCOUNT_STORE.store_challenge(email, "registration", bytes_to_base64url(options.challenge))
        return {"options": webauthn.options_to_json(options)}, HTTPStatus.OK, None

    def register_complete(self, body: dict[str, Any], headers: Any = None, client_address: tuple[str, int] | None = None) -> tuple[dict[str, Any], HTTPStatus, str | None]:
        ip = _client_ip(headers, client_address)
        ua = str(headers.get("User-Agent", "")).strip() if headers else ""
        email = str(body.get("email", "")).strip().lower()
        credential = body.get("credential")
        nickname = str(body.get("nickname", "Primary Key")).strip() or "Primary Key"
        if not email or not isinstance(credential, dict):
            return {"error": "email and credential are required"}, HTTPStatus.BAD_REQUEST, None

        challenge_b64 = FLEET_ACCOUNT_STORE.consume_challenge(email, "registration")
        if not challenge_b64:
            return {"error": "registration challenge expired -- please try again"}, HTTPStatus.BAD_REQUEST, None

        try:
            verified = webauthn.verify_registration_response(
                credential=credential,
                expected_challenge=webauthn.base64url_to_bytes(challenge_b64),
                expected_rp_id=RP_ID,
                expected_origin=EXPECTED_ORIGIN,
            )
        except InvalidRegistrationResponse as exc:
            return {"error": f"passkey registration failed: {exc}"}, HTTPStatus.BAD_REQUEST, None

        try:
            account = FLEET_ACCOUNT_STORE.create_account(email)
        except FleetAccountStoreError as exc:
            return {"error": str(exc)}, HTTPStatus.CONFLICT, None

        FLEET_ACCOUNT_STORE.add_passkey(
            account.account_id,
            bytes_to_base64url(verified.credential_id),
            bytes_to_base64url(verified.credential_public_key),
            verified.sign_count,
            ",".join(credential.get("response", {}).get("transports", []) or []),
            nickname=nickname,
        )
        FLEET_ACCOUNT_STORE.record_audit_event(
            account.account_id, email, "passkey_registered", f"New passkey registered ({nickname})", ip, ua
        )
        send_security_alert(
            email,
            "Neuer Passkey registriert",
            f"Ein neuer Passkey ('{nickname}') wurde erfolgreich für dein Flotten-Konto registriert.",
            ip,
            ua,
        )
        token = FLEET_ACCOUNT_STORE.create_session(account.account_id)
        return (
            {"account_id": account.account_id, "email": account.email, "owner_key": account.owner_key},
            HTTPStatus.CREATED,
            _session_cookie_header(token),
        )

    def login_begin(self, body: dict[str, Any], headers: Any = None, client_address: tuple[str, int] | None = None) -> tuple[dict[str, Any], HTTPStatus, str | None]:
        ip = _client_ip(headers, client_address)
        if not RATE_LIMITER.is_allowed(f"login_begin:{ip}"):
            return {"error": "Too many requests. Please try again later."}, HTTPStatus.TOO_MANY_REQUESTS, None

        email = str(body.get("email", "")).strip().lower()
        account = FLEET_ACCOUNT_STORE.get_account_by_email(email) if email else None
        if account is None:
            return {"error": "no account found for this email"}, HTTPStatus.NOT_FOUND, None

        passkeys = FLEET_ACCOUNT_STORE.list_passkeys(account.account_id)
        if not passkeys:
            return {"error": "this account has no registered passkeys -- use magic link login"}, HTTPStatus.NOT_FOUND, None

        options = webauthn.generate_authentication_options(
            rp_id=RP_ID,
            allow_credentials=[
                PublicKeyCredentialDescriptor(id=webauthn.base64url_to_bytes(pk.credential_id))
                for pk in passkeys
            ],
            user_verification=UserVerificationRequirement.PREFERRED,
        )
        FLEET_ACCOUNT_STORE.store_challenge(email, "authentication", bytes_to_base64url(options.challenge))
        return {"options": webauthn.options_to_json(options)}, HTTPStatus.OK, None

    def login_complete(self, body: dict[str, Any], headers: Any = None, client_address: tuple[str, int] | None = None) -> tuple[dict[str, Any], HTTPStatus, str | None]:
        ip = _client_ip(headers, client_address)
        ua = str(headers.get("User-Agent", "")).strip() if headers else ""
        email = str(body.get("email", "")).strip().lower()
        credential = body.get("credential")
        if not email or not isinstance(credential, dict):
            return {"error": "email and credential are required"}, HTTPStatus.BAD_REQUEST, None

        account = FLEET_ACCOUNT_STORE.get_account_by_email(email)
        challenge_b64 = FLEET_ACCOUNT_STORE.consume_challenge(email, "authentication")
        if account is None or not challenge_b64:
            return {"error": "login challenge expired -- please try again"}, HTTPStatus.BAD_REQUEST, None

        credential_id = str(credential.get("id", ""))
        passkey = FLEET_ACCOUNT_STORE.get_passkey(credential_id)
        if passkey is None or passkey.account_id != account.account_id:
            FLEET_ACCOUNT_STORE.record_audit_event(
                account.account_id, email, "login_failed", "Unrecognized passkey credential", ip, ua
            )
            return {"error": "unrecognized passkey"}, HTTPStatus.UNAUTHORIZED, None

        try:
            verified = webauthn.verify_authentication_response(
                credential=credential,
                expected_challenge=webauthn.base64url_to_bytes(challenge_b64),
                expected_rp_id=RP_ID,
                expected_origin=EXPECTED_ORIGIN,
                credential_public_key=webauthn.base64url_to_bytes(passkey.public_key),
                credential_current_sign_count=passkey.sign_count,
            )
        except InvalidAuthenticationResponse as exc:
            FLEET_ACCOUNT_STORE.record_audit_event(
                account.account_id, email, "login_failed", f"Verification exception: {exc}", ip, ua
            )
            return {"error": f"passkey login failed: {exc}"}, HTTPStatus.UNAUTHORIZED, None

        FLEET_ACCOUNT_STORE.update_sign_count(credential_id, verified.new_sign_count)
        token = FLEET_ACCOUNT_STORE.create_session(account.account_id)
        FLEET_ACCOUNT_STORE.record_audit_event(
            account.account_id, email, "login_success", f"Passkey login ({passkey.nickname or 'Passkey'})", ip, ua
        )
        return (
            {"account_id": account.account_id, "email": account.email, "owner_key": account.owner_key},
            HTTPStatus.OK,
            _session_cookie_header(token),
        )

    # -- Magic Links --------------------------------------------------------

    def request_magic_link(self, body: dict[str, Any], headers: Any = None, client_address: tuple[str, int] | None = None) -> tuple[dict[str, Any], HTTPStatus, str | None]:
        ip = _client_ip(headers, client_address)
        email = str(body.get("email", "")).strip().lower()
        if not email or "@" not in email:
            return {"error": "a valid email address is required"}, HTTPStatus.BAD_REQUEST, None

        if not MAGIC_LINK_RATE_LIMITER.is_allowed(f"magic:{email}"):
            return {"error": "Zu viele Anfragen. Bitte warte einige Minuten, bevor du einen neuen Link anforderst."}, HTTPStatus.TOO_MANY_REQUESTS, None

        raw_token = FLEET_ACCOUNT_STORE.create_magic_link_token(email, ttl_minutes=15)
        magic_url = f"{EXPECTED_ORIGIN}/fleet?magic_token={raw_token}"
        sent = send_magic_link(email, magic_url, expires_minutes=15)
        logger.info("Dispatched magic link to %s (success=%s)", email, sent)

        return {
            "status": "ok",
            "message": "Ein sicherer Login-Link wurde per E-Mail an deine Adresse gesendet.",
        }, HTTPStatus.OK, None

    def verify_magic_link(self, body: dict[str, Any], headers: Any = None, client_address: tuple[str, int] | None = None) -> tuple[dict[str, Any], HTTPStatus, str | None]:
        ip = _client_ip(headers, client_address)
        ua = str(headers.get("User-Agent", "")).strip() if headers else ""
        raw_token = str(body.get("magic_token", "")).strip()
        if not raw_token:
            return {"error": "magic_token is required"}, HTTPStatus.BAD_REQUEST, None

        account = FLEET_ACCOUNT_STORE.verify_magic_link_token(raw_token)
        if account is None:
            return {"error": "Dieser Login-Link ist ungültig oder abgelaufen. Bitte fordere einen neuen an."}, HTTPStatus.UNAUTHORIZED, None

        token = FLEET_ACCOUNT_STORE.create_session(account.account_id)
        FLEET_ACCOUNT_STORE.record_audit_event(
            account.account_id, account.email, "login_magic_link", "E-Mail Magic-Link Login erfolgreich", ip, ua
        )
        send_security_alert(
            account.email,
            "Neuer Login über Magic-Link",
            "Du hast dich erfolgreich per E-Mail-Einmallink in deinem Flotten-Cockpit angemeldet.",
            ip,
            ua,
        )
        return (
            {"account_id": account.account_id, "email": account.email, "owner_key": account.owner_key},
            HTTPStatus.OK,
            _session_cookie_header(token),
        )

    # -- Passkey Management -------------------------------------------------

    def list_passkeys(self, headers: Any) -> tuple[dict[str, Any], HTTPStatus, str | None]:
        account = session_account_from_headers(headers)
        if account is None:
            return {"error": "not authenticated"}, HTTPStatus.UNAUTHORIZED, None

        passkeys = FLEET_ACCOUNT_STORE.list_passkeys(account.account_id)
        return {
            "passkeys": [
                {
                    "credential_id": pk.credential_id,
                    "nickname": pk.nickname or "Passkey",
                    "created_at": pk.created_at,
                    "last_used_at": pk.last_used_at or pk.created_at,
                    "sign_count": pk.sign_count,
                }
                for pk in passkeys
            ]
        }, HTTPStatus.OK, None

    def delete_passkey(self, headers: Any, body: dict[str, Any], client_address: tuple[str, int] | None = None) -> tuple[dict[str, Any], HTTPStatus, str | None]:
        account = session_account_from_headers(headers)
        if account is None:
            return {"error": "not authenticated"}, HTTPStatus.UNAUTHORIZED, None

        credential_id = str(body.get("credential_id", "")).strip()
        if not credential_id:
            return {"error": "credential_id is required"}, HTTPStatus.BAD_REQUEST, None

        passkeys = FLEET_ACCOUNT_STORE.list_passkeys(account.account_id)
        if len(passkeys) <= 1:
            return {"error": "Du kannst deinen einzigen Passkey nicht löschen. Registriere zuerst einen Ersatzschlüssel."}, HTTPStatus.BAD_REQUEST, None

        deleted = FLEET_ACCOUNT_STORE.delete_passkey(account.account_id, credential_id)
        ip = _client_ip(headers, client_address)
        ua = str(headers.get("User-Agent", "")).strip() if headers else ""
        FLEET_ACCOUNT_STORE.record_audit_event(
            account.account_id, account.email, "passkey_deleted", f"Passkey {credential_id[:8]}... gelöscht", ip, ua
        )
        return {"status": "ok", "deleted": deleted}, HTTPStatus.OK, None

    def rename_passkey(self, headers: Any, body: dict[str, Any]) -> tuple[dict[str, Any], HTTPStatus, str | None]:
        account = session_account_from_headers(headers)
        if account is None:
            return {"error": "not authenticated"}, HTTPStatus.UNAUTHORIZED, None

        credential_id = str(body.get("credential_id", "")).strip()
        nickname = str(body.get("nickname", "")).strip()
        if not credential_id or not nickname:
            return {"error": "credential_id and nickname are required"}, HTTPStatus.BAD_REQUEST, None

        renamed = FLEET_ACCOUNT_STORE.rename_passkey(account.account_id, credential_id, nickname)
        return {"status": "ok", "renamed": renamed}, HTTPStatus.OK, None

    # -- Enrollment Tokens & Audit Log --------------------------------------

    def create_enrollment_token(self, headers: Any) -> tuple[dict[str, Any], HTTPStatus, str | None]:
        account = session_account_from_headers(headers)
        if account is None:
            return {"error": "not authenticated"}, HTTPStatus.UNAUTHORIZED, None

        token = FLEET_ACCOUNT_STORE.create_enrollment_token(account.account_id, ttl_minutes=30)
        return {"enrollment_token": token, "expires_in_minutes": 30}, HTTPStatus.OK, None

    def get_audit_log(self, headers: Any) -> tuple[dict[str, Any], HTTPStatus, str | None]:
        account = session_account_from_headers(headers)
        if account is None:
            return {"error": "not authenticated"}, HTTPStatus.UNAUTHORIZED, None

        logs = FLEET_ACCOUNT_STORE.get_audit_log(account.account_id, limit=50)
        return {"audit_log": logs}, HTTPStatus.OK, None

    def logout(self, headers: Any) -> tuple[dict[str, Any], HTTPStatus, str | None]:
        raw = headers.get("Cookie", "")
        cookie: SimpleCookie = SimpleCookie()
        try:
            cookie.load(raw)
        except Exception:
            pass
        morsel = cookie.get(SESSION_COOKIE_NAME)
        if morsel is not None:
            FLEET_ACCOUNT_STORE.delete_session(morsel.value)
        return {"status": "ok"}, HTTPStatus.OK, _session_cookie_header("", clear=True)
