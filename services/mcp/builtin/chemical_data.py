# SPDX-License-Identifier: Apache-2.0
"""
PubChem Chemical, Molecular & Pharmacological Intelligence Tool.
Fetches chemical formulas, IUPAC names, molecular weights, SMILES, and compound properties from NIH PubChem.
Supports generic single and multi-compound queries with concurrent execution.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import re
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ComputeMesh/1.2 (https://mesh.inetconnector.com)"

DE_TRANSLATIONS: Dict[str, str] = {
    "koffein": "caffeine",
    "coffein": "caffeine",
    "traubenzucker": "glucose",
    "kochsalz": "sodium chloride",
    "salzsäure": "hydrochloric acid",
    "salzsaeure": "hydrochloric acid",
    "schwefelsäure": "sulfuric acid",
    "schwefelsaeure": "sulfuric acid",
    "salpetersäure": "nitric acid",
    "salpetersaeure": "nitric acid",
    "kohlendioxid": "carbon dioxide",
    "kohlenmonoxid": "carbon monoxide",
    "wasserstoffperoxid": "hydrogen peroxide",
    "essigsäure": "acetic acid",
    "essigsaeure": "acetic acid",
    "wasser": "water",
    "sauerstoff": "oxygen",
    "stickstoff": "nitrogen",
    "methan": "methane",
    "traubenzucker": "glucose",
    "fruchtzucker": "fructose",
    "rohrzucker": "sucrose",
    "zucker": "sucrose",
    "kalk": "calcium carbonate",
    "natron": "sodium bicarbonate",
    "backpulver": "sodium bicarbonate",
    "paracetamol": "acetaminophen",
    "ibuprofen": "ibuprofen",
    "aspirin": "aspirin",
    "acetylsalicylsäure": "aspirin",
    "acetylsalicylsaeure": "aspirin",
}


def _split_compound_queries(raw: str) -> List[str]:
    """Splits compound queries containing multiple items."""
    cleaned = re.sub(r"^(?:chemische\s+formel\s+(?:von|fuer|für)\s+|eigenschaften\s+(?:von|fuer|für)\s+|molekül\s+(?:von\s+)?|molekulargewicht\s+(?:von\s+)?|struktur\s+(?:von\s+)?|verbindung\s+)", "", raw, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"[\?\.!]$", "", cleaned).strip()
    parts = re.split(r",|\s+und\s+|\s+sowie\s+|\s+and\s+|\s*\+\s*", cleaned, flags=re.IGNORECASE)
    results = []
    for p in parts:
        token = p.strip()
        if token and len(token) >= 2:
            results.append(token)
    return results if results else ([raw.strip()] if raw.strip() else [])


def _fetch_single_compound(search_term: str, timeout: float = 6.0) -> Dict[str, Any]:
    clean_term = search_term.strip()
    lookup_str = DE_TRANSLATIONS.get(clean_term.lower(), clean_term)
    encoded = urllib.parse.quote(lookup_str)

    url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{encoded}/property/MolecularFormula,MolecularWeight,IUPACName,CanonicalSMILES,InChIKey/JSON"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        props_table = data.get("PropertyTable", {}).get("Properties", [])
        if not props_table:
            return {"error": f"Keine chemische Verbindung für '{clean_term}' in PubChem gefunden.", "compound_name": clean_term}

        props = props_table[0]
        formula = props.get("MolecularFormula", "Unbekannt")
        weight = props.get("MolecularWeight", "Unbekannt")
        iupac = props.get("IUPACName", "Unbekannt")
        smiles = props.get("CanonicalSMILES", "Unbekannt")
        cid = props.get("CID")

        summary = (
            f"**{clean_term.capitalize()}** (PubChem CID {cid}):\n"
            f"- **Summenformel**: {formula}\n"
            f"- **Molekulargewicht**: {weight} g/mol\n"
            f"- **IUPAC-Name**: {iupac}\n"
            f"- **Canonical SMILES**: `{smiles}`"
        )

        return {
            "compound_name": clean_term,
            "pubchem_cid": cid,
            "molecular_formula": formula,
            "molecular_weight_g_mol": weight,
            "iupac_name": iupac,
            "canonical_smiles": smiles,
            "inchikey": props.get("InChIKey", ""),
            "summary": summary,
            "source": "NIH PubChem PUG REST API",
        }
    except Exception as e:
        return {"error": f"Fehler bei PubChem-Abfrage für '{clean_term}': {str(e)}", "compound_name": clean_term}


def lookup_chemical_compound(
    compound_name: str = "",
    name: str = "",
    query: str = "",
    timeout: float = 6.0,
) -> Dict[str, Any]:
    """
    Looks up verified chemical compound properties (molecular formula, molecular weight, IUPAC name, SMILES) via NIH PubChem.
    Supports single or multiple compound names concurrently.
    """
    raw_query = (compound_name or name or query or "").strip()
    if not raw_query:
        return {"error": "Name der chemischen Verbindung darf nicht leer sein (z. B. 'Aspirin', 'Caffeine', 'Ethanol', 'Paracetamol')."}

    compounds = _split_compound_queries(raw_query)
    if len(compounds) > 1:
        with ThreadPoolExecutor(max_workers=min(len(compounds), 6)) as pool:
            futures = [pool.submit(_fetch_single_compound, c, timeout) for c in compounds]
            results = [f.result() for f in futures]
        return {
            "multiple_compounds": True,
            "query": raw_query,
            "compounds": results,
            "source": "NIH PubChem PUG REST API",
        }

    return _fetch_single_compound(compounds[0] if compounds else raw_query, timeout=timeout)


# Backwards-compatible alias
lookup_chemistry = lookup_chemical_compound
