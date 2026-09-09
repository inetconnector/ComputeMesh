# SPDX-License-Identifier: Apache-2.0
"""Legal-entity lookup using the public GLEIF Global LEI Index."""

from __future__ import annotations

import urllib.parse
from typing import Any, Dict

from .http_json import ProviderError, fetch_json

GLEIF_HOST = "api.gleif.org"


def _address(value: Any) -> Dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    lines = value.get("addressLines")
    return {
        "lines": lines if isinstance(lines, list) else [],
        "city": value.get("city"),
        "region": value.get("region"),
        "postal_code": value.get("postalCode"),
        "country": value.get("country"),
    }


def lookup_company(
    name: str = "",
    country: str = "",
    limit: int = 5,
    timeout: float = 8.0,
) -> Dict[str, Any]:
    """Search authoritative LEI records by legal entity name.

    GLEIF is strongest for entities that have an LEI; absence from this result is
    therefore not proof that a company does not exist.
    """
    company_name = str(name or "").strip()
    country_code = str(country or "").strip().upper()
    if not company_name:
        return {"error": "Unternehmensname (name) darf nicht leer sein."}
    if len(company_name) > 250:
        return {"error": "Unternehmensname ist zu lang (maximal 250 Zeichen)."}
    if country_code and (len(country_code) != 2 or not country_code.isalpha()):
        return {"error": "country muss ein zweistelliger ISO-Ländercode sein (z. B. DE, US, CH)."}

    try:
        result_limit = max(1, min(10, int(limit)))
    except (TypeError, ValueError):
        return {"error": "limit muss eine ganze Zahl zwischen 1 und 10 sein."}

    params: dict[str, Any] = {
        "filter[entity.legalName]": company_name,
        "page[size]": result_limit,
    }
    if country_code:
        params["filter[entity.legalAddress.country]"] = country_code
    url = f"https://{GLEIF_HOST}/api/v1/lei-records?{urllib.parse.urlencode(params)}"

    try:
        payload = fetch_json(url, allowed_hosts={GLEIF_HOST}, timeout=timeout)
    except ProviderError as exc:
        return {"error": str(exc), "provider": "GLEIF Global LEI Index"}

    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        return {"error": "GLEIF lieferte ein unerwartetes Antwortformat.", "provider": "GLEIF Global LEI Index"}

    companies = []
    for record in payload["data"][:result_limit]:
        if not isinstance(record, dict):
            continue
        attrs = record.get("attributes")
        if not isinstance(attrs, dict):
            continue
        entity = attrs.get("entity") if isinstance(attrs.get("entity"), dict) else {}
        registration = attrs.get("registration") if isinstance(attrs.get("registration"), dict) else {}
        legal_name = entity.get("legalName") if isinstance(entity.get("legalName"), dict) else {}
        other_names = entity.get("otherNames") if isinstance(entity.get("otherNames"), list) else []
        companies.append({
            "lei": attrs.get("lei") or record.get("id"),
            "legal_name": legal_name.get("name"),
            "other_names": [x.get("name") for x in other_names if isinstance(x, dict) and x.get("name")],
            "entity_status": entity.get("status"),
            "legal_jurisdiction": entity.get("jurisdiction"),
            "entity_category": entity.get("category"),
            "legal_address": _address(entity.get("legalAddress")),
            "headquarters_address": _address(entity.get("headquartersAddress")),
            "registration_status": registration.get("status"),
            "initial_registration_date": registration.get("initialRegistrationDate"),
            "last_update_date": registration.get("lastUpdateDate"),
            "next_renewal_date": registration.get("nextRenewalDate"),
        })

    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    pagination = meta.get("pagination") if isinstance(meta.get("pagination"), dict) else {}
    return {
        "query": company_name,
        "country": country_code or None,
        "results_count": len(companies),
        "total_available": pagination.get("total"),
        "companies": companies,
        "source": "GLEIF Global LEI Index",
        "coverage_note": "GLEIF enthält Rechtsträger mit Legal Entity Identifier (LEI); fehlende Treffer beweisen keine Nichtexistenz.",
    }
