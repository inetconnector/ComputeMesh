# SPDX-License-Identifier: Apache-2.0
"""
PubChem Chemical, Molecular & Pharmacological Intelligence Tool.
Fetches chemical formulas, IUPAC names, molecular weights, SMILES, and compound properties from NIH PubChem.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ComputeMesh/1.2 (https://mesh.inetconnector.com)"


def lookup_chemical_compound(
    compound_name: str = "",
    name: str = "",
    query: str = "",
    timeout: float = 6.0,
) -> Dict[str, Any]:
    """
    Looks up verified chemical compound properties (molecular formula, molecular weight, IUPAC name, SMILES) via NIH PubChem.
    """
    search_term = (compound_name or name or query or "").strip()
    if not search_term:
        return {"error": "Name der chemischen Verbindung darf nicht leer sein (z. B. 'Aspirin', 'Caffeine', 'Ethanol', 'Paracetamol')."}

    # Common German-to-English chemical translations
    DE_TRANSLATIONS = {
        "koffein": "caffeine",
        "coffein": "caffeine",
        "traubenzucker": "glucose",
        "kochsalz": "sodium chloride",
        "salzsäure": "hydrochloric acid",
        "schwefelsäure": "sulfuric acid",
        "salpetersäure": "nitric acid",
        "kohlendioxid": "carbon dioxide",
        "wasserstoffperoxid": "hydrogen peroxide",
        "essigsäure": "acetic acid",
    }
    lookup_str = DE_TRANSLATIONS.get(search_term.lower(), search_term)
    encoded = urllib.parse.quote(lookup_str)

    url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{encoded}/property/MolecularFormula,MolecularWeight,IUPACName,CanonicalSMILES,InChIKey/JSON"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        props_table = data.get("PropertyTable", {}).get("Properties", [])
        if not props_table:
            return {"error": f"Keine chemische Verbindung für '{search_term}' in PubChem gefunden."}

        props = props_table[0]
        formula = props.get("MolecularFormula", "Unbekannt")
        weight = props.get("MolecularWeight", "Unbekannt")
        iupac = props.get("IUPACName", "Unbekannt")
        smiles = props.get("CanonicalSMILES", "Unbekannt")
        cid = props.get("CID")

        summary = (
            f"**{search_term.capitalize()}** (PubChem CID {cid}):\n"
            f"- **Summenformel**: {formula}\n"
            f"- **Molekulargewicht**: {weight} g/mol\n"
            f"- **IUPAC-Name**: {iupac}\n"
            f"- **Canonical SMILES**: `{smiles}`"
        )

        return {
            "compound_name": search_term,
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
        return {"error": f"Fehler bei PubChem-Abfrage für '{search_term}': {str(e)}"}


# Backwards-compatible alias
lookup_chemistry = lookup_chemical_compound
