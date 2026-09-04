"""Passkey (WebAuthn) login for remote fleet administration.

A portal account has no password: registering an email creates a passkey
credential (Face ID / Windows Hello / a hardware key) that is the only way
to sign in. On first registration the account is issued a generated
`owner_key` -- the same shared secret already used by
tools/appliance/appliance_config.py and the per-node dashboard's "Owner Key"
field -- so pasting it into a node's dashboard is what actually binds that
node into the signed-in account's fleet (services/billing/owner_accounts.py
still owns that binding; this module never writes to it directly).

Session model: an httponly, samesite=Lax cookie holding an opaque session
token that FleetAccountStore resolves to an account. There is no CSRF token
because every state-changing route here requires a valid session cookie AND
is same-site by construction (no cross-origin form posts are meaningful
against a JSON API that ignores non-JSON bodies).
"""
from __future__ import annotations

from http import HTTPStatus
from http.cookies import SimpleCookie
import os
from pathlib import Path
import sys
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

    def register_begin(self, body: dict[str, Any]) -> tuple[dict[str, Any], HTTPStatus, str | None]:
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

    def register_complete(self, body: dict[str, Any]) -> tuple[dict[str, Any], HTTPStatus, str | None]:
        email = str(body.get("email", "")).strip().lower()
        credential = body.get("credential")
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
        )
        token = FLEET_ACCOUNT_STORE.create_session(account.account_id)
        return (
            {"account_id": account.account_id, "email": account.email, "owner_key": account.owner_key},
            HTTPStatus.CREATED,
            _session_cookie_header(token),
        )

    def login_begin(self, body: dict[str, Any]) -> tuple[dict[str, Any], HTTPStatus, str | None]:
        email = str(body.get("email", "")).strip().lower()
        account = FLEET_ACCOUNT_STORE.get_account_by_email(email) if email else None
        if account is None:
            return {"error": "no account found for this email"}, HTTPStatus.NOT_FOUND, None

        passkeys = FLEET_ACCOUNT_STORE.list_passkeys(account.account_id)
        if not passkeys:
            return {"error": "this account has no registered passkeys"}, HTTPStatus.NOT_FOUND, None

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

    def login_complete(self, body: dict[str, Any]) -> tuple[dict[str, Any], HTTPStatus, str | None]:
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
            return {"error": f"passkey login failed: {exc}"}, HTTPStatus.UNAUTHORIZED, None

        FLEET_ACCOUNT_STORE.update_sign_count(credential_id, verified.new_sign_count)
        token = FLEET_ACCOUNT_STORE.create_session(account.account_id)
        return (
            {"account_id": account.account_id, "email": account.email},
            HTTPStatus.OK,
            _session_cookie_header(token),
        )

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
