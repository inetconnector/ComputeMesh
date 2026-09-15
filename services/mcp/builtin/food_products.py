# SPDX-License-Identifier: Apache-2.0
"""
Open Food Facts Nutritional & Ingredient Intelligence Tool.
Retrieves ingredients, allergens, Nutri-Score, energy, and macronutrients for food items and EAN barcodes.
Supports generic single and multi-product queries with concurrent execution.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import re
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ComputeMesh/1.2 (https://mesh.inetconnector.com)"

PRODUCT_ALIASES: Dict[str, str] = {
    "hafermilch": "oat milk",
    "haferdrink": "oat milk",
    "sojamilch": "soy milk",
    "sojadrink": "soy milk",
    "mandelmilch": "almond milk",
    "mandeldrink": "almond milk",
    "erbsenmilch": "pea milk",
    "reismilch": "rice milk",
    "kokosmilch": "coconut milk",
}


def _split_product_queries(raw: str) -> List[str]:
    """Splits queries containing multiple food items."""
    cleaned = re.sub(r"^(?:nährwerte\s+(?:von|fuer|für)\s+|inhaltsstoffe\s+(?:von|fuer|für)\s+|zutaten\s+(?:von|fuer|für)\s+|kalorien\s+(?:in|von)\s+|lebensmittel\s+)", "", raw, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"[\?\.!]$", "", cleaned).strip()
    parts = re.split(r",|\s+und\s+|\s+sowie\s+|\s+and\s+|\s*\+\s*", cleaned, flags=re.IGNORECASE)
    results = []
    for p in parts:
        token = p.strip()
        if token and len(token) >= 2:
            results.append(token)
    return results if results else ([raw.strip()] if raw.strip() else [])


def _fetch_by_barcode(barcode: str, timeout: float = 6.0) -> Optional[Dict[str, Any]]:
    """Fetches food product by exact EAN/UPC barcode."""
    clean_code = barcode.strip().replace(" ", "").replace("-", "")
    url = f"https://world.openfoodfacts.org/api/v2/product/{clean_code}.json"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("status") == 1 and "product" in data:
                return data["product"]
    except Exception:
        pass
    return None


def _search_by_name(query: str, timeout: float = 6.0) -> Optional[Dict[str, Any]]:
    """Searches food product by keyword."""
    lookup_term = PRODUCT_ALIASES.get(query.strip().lower(), query.strip())
    encoded = urllib.parse.quote(lookup_term)
    url = f"https://world.openfoodfacts.org/cgi/search.pl?search_terms={encoded}&search_simple=1&action=process&json=1&page_size=1"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            products = data.get("products", [])
            if products and len(products) > 0:
                return products[0]
    except Exception:
        pass
    return None


def _fetch_single_product(search_term: str, timeout: float = 7.0) -> Dict[str, Any]:
    clean_term = search_term.strip()
    prod_data = None
    if clean_term.isdigit() and len(clean_term) >= 8:
        prod_data = _fetch_by_barcode(clean_term, timeout=timeout)

    if not prod_data:
        prod_data = _search_by_name(clean_term, timeout=timeout)

    if not prod_data:
        return {"error": f"Kein Lebensmittelprodukt für '{clean_term}' in der Open Food Facts Datenbank gefunden.", "product_name": clean_term}

    name = prod_data.get("product_name_de") or prod_data.get("product_name") or clean_term
    brands = prod_data.get("brands", "Unbekannter Hersteller")
    nutriscore = (prod_data.get("nutriscore_grade") or "Unbekannt").upper()
    ecoscore = (prod_data.get("ecoscore_grade") or "Unbekannt").upper()
    ingredients = prod_data.get("ingredients_text_de") or prod_data.get("ingredients_text") or "Keine Angabe"
    allergens = prod_data.get("allergens_from_ingredients") or prod_data.get("allergens") or "Keine deklariert"

    nutriments = prod_data.get("nutriments", {})
    energy_kcal = nutriments.get("energy-kcal_100g", nutriments.get("energy-kcal_value"))
    fat = nutriments.get("fat_100g", nutriments.get("fat"))
    saturated_fat = nutriments.get("saturated-fat_100g")
    carbs = nutriments.get("carbohydrates_100g", nutriments.get("carbohydrates"))
    sugars = nutriments.get("sugars_100g", nutriments.get("sugars"))
    proteins = nutriments.get("proteins_100g", nutriments.get("proteins"))
    salt = nutriments.get("salt_100g", nutriments.get("salt"))

    nutrition_table = {
        "brennwert_kcal_100g": energy_kcal,
        "fett_g_100g": fat,
        "gesaettigte_fettsaeuren_g": saturated_fat,
        "kohlenhydrate_g_100g": carbs,
        "zucker_g_100g": sugars,
        "eiweiss_g_100g": proteins,
        "salz_g_100g": salt,
    }

    summary = (
        f"**{name}** (Marke: {brands}):\n"
        f"- **Nutri-Score**: {nutriscore} | **Eco-Score**: {ecoscore}\n"
        f"- **Nährwerte pro 100g**: {energy_kcal or '?'} kcal | Fett: {fat or '?'}g | Kohlenhydrate: {carbs or '?'}g (Zucker: {sugars or '?'}g) | Eiweiß: {proteins or '?'}g | Salz: {salt or '?'}g\n"
        f"- **Allergene**: {allergens}\n"
        f"- **Zutaten**: {ingredients[:300]}{'...' if len(ingredients) > 300 else ''}"
    )

    return {
        "product_name": name,
        "brand": brands,
        "barcode": prod_data.get("code", clean_term),
        "nutriscore": nutriscore,
        "ecoscore": ecoscore,
        "ingredients": ingredients,
        "allergens": allergens,
        "nutrition_per_100g": nutrition_table,
        "summary": summary,
        "source": "Open Food Facts Open Database",
    }


def lookup_food_product(
    product_name: str = "",
    barcode: str = "",
    query: str = "",
    timeout: float = 7.0,
) -> Dict[str, Any]:
    """
    Looks up food ingredients, allergens, Nutri-Score, calories, and macronutrients per 100g via Open Food Facts.
    Supports single or multiple product queries concurrently.
    """
    raw_query = (product_name or barcode or query or "").strip()
    if not raw_query:
        return {"error": "Produktname oder Barcode (EAN) darf nicht leer sein (z. B. 'Nutella', 'Hafermilch', '3017620422003')."}

    # If it's a barcode, lookup directly
    if raw_query.isdigit() and len(raw_query) >= 8:
        return _fetch_single_product(raw_query, timeout=timeout)

    products = _split_product_queries(raw_query)
    if len(products) > 1:
        with ThreadPoolExecutor(max_workers=min(len(products), 6)) as pool:
            futures = [pool.submit(_fetch_single_product, p, timeout) for p in products]
            results = [f.result() for f in futures]
        return {
            "multiple_products": True,
            "query": raw_query,
            "products": results,
            "source": "Open Food Facts Open Database",
        }

    return _fetch_single_product(products[0] if products else raw_query, timeout=timeout)


# Backwards-compatible alias
lookup_nutrition = lookup_food_product
