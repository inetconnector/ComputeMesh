# SPDX-License-Identifier: Apache-2.0
"""
Open Food Facts Nutritional & Ingredient Intelligence Tool.
Retrieves ingredients, allergens, Nutri-Score, energy, and macronutrients for food items and EAN barcodes.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ComputeMesh/1.2 (https://mesh.inetconnector.com)"


def _fetch_by_barcode(barcode: str, timeout: float = 5.0) -> Optional[Dict[str, Any]]:
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


def _search_by_name(query: str, timeout: float = 5.0) -> Optional[Dict[str, Any]]:
    """Searches food product by keyword."""
    encoded = urllib.parse.quote(query.strip())
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


def lookup_food_product(
    product_name: str = "",
    barcode: str = "",
    query: str = "",
    timeout: float = 7.0,
) -> Dict[str, Any]:
    """
    Looks up food ingredients, allergens, Nutri-Score, calories, and macronutrients per 100g via Open Food Facts.
    """
    search_term = (product_name or barcode or query or "").strip()
    if not search_term:
        return {"error": "Produktname oder Barcode (EAN) darf nicht leer sein (z. B. 'Nutella', 'Hafermilch', '3017620422003')."}

    # If numeric barcode
    prod_data = None
    if search_term.isdigit() and len(search_term) >= 8:
        prod_data = _fetch_by_barcode(search_term, timeout=timeout / 2)

    if not prod_data:
        prod_data = _search_by_name(search_term, timeout=timeout / 2)

    if not prod_data:
        return {"error": f"Kein Lebensmittelprodukt für '{search_term}' in der Open Food Facts Datenbank gefunden."}

    name = prod_data.get("product_name_de") or prod_data.get("product_name") or search_term
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
        "barcode": prod_data.get("code", search_term),
        "nutriscore": nutriscore,
        "ecoscore": ecoscore,
        "ingredients": ingredients,
        "allergens": allergens,
        "nutrition_per_100g": nutrition_table,
        "summary": summary,
        "source": "Open Food Facts Open Database",
    }


# Backwards-compatible alias
lookup_nutrition = lookup_food_product
