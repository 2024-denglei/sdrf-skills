"""Mapping from SDRF column names to expected ontology sources.

Derived from TERMS.tsv `values` field and the sdrf-terms SKILL.md.
Used as a fallback when the spec submodule is not initialized.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# Maps characteristics/comment inner names -> list of valid ontology prefixes.
# Order matters: first is preferred.
COLUMN_ONTOLOGY_MAP: dict[str, list[str]] = {
    # Biological characteristics
    "organism": ["NCBITaxon"],
    "disease": ["MONDO", "EFO", "DOID", "PATO"],
    "organism part": ["UBERON", "BTO"],
    "cell type": ["CL", "BTO"],
    "cell line": ["CLO", "BTO", "EFO"],
    "developmental stage": ["UBERON", "HsapDv"],
    "ancestry category": ["HANCESTRO"],
    "sex": [],  # controlled vocabulary, not ontology
    "age": [],  # free format (e.g. 58Y)

    # Technical metadata (comment columns)
    "instrument": ["MS"],
    "modification parameters": ["UNIMOD"],
    "cleavage agent details": ["MS"],
    "label": ["MS"],
    "dissociation method": ["MS"],
    "precursor mass tolerance": [],
    "fragment mass tolerance": [],
}

# Known UNIMOD accession -> name mappings for swap detection.
# These are the most commonly confused pairs.
UNIMOD_KNOWN: dict[str, str] = {
    "UNIMOD:1": "Acetyl",
    "UNIMOD:4": "Carbamidomethyl",
    "UNIMOD:5": "Carbamyl",
    "UNIMOD:7": "Deamidated",
    "UNIMOD:21": "Phospho",
    "UNIMOD:34": "Methyl",
    "UNIMOD:35": "Oxidation",
    "UNIMOD:36": "Dimethyl",
    "UNIMOD:37": "Trimethyl",
    "UNIMOD:122": "Formyl",
    "UNIMOD:188": "Label:13C(6)",
    "UNIMOD:199": "Label:13C(6)15N(2)",
    "UNIMOD:259": "Label:13C(6)15N(4)",
    "UNIMOD:267": "Silac:2H(4)",
    "UNIMOD:268": "iTRAQ4plex",
    "UNIMOD:304": "iTRAQ8plex",
    "UNIMOD:312": "Cation:Na",
    "UNIMOD:354": "TMT6plex",
    "UNIMOD:374": "Propionamide",
    "UNIMOD:737": "TMT6plex",
    "UNIMOD:2016": "TMTpro",
}

# Common UNIMOD swap pairs (wrong -> correct)
UNIMOD_SWAPS: dict[tuple[str, str], tuple[str, str]] = {
    # (wrong_accession, wrong_name) -> (correct_accession, correct_name)
    ("UNIMOD:21", "Acetyl"): ("UNIMOD:1", "Acetyl"),
    ("UNIMOD:1", "Phospho"): ("UNIMOD:21", "Phospho"),
    ("UNIMOD:34", "Oxidation"): ("UNIMOD:35", "Oxidation"),
    ("UNIMOD:35", "Methyl"): ("UNIMOD:34", "Methyl"),
}

# Reserved words in SDRF
RESERVED_WORDS = {
    "not available",
    "not applicable",
}

# Common wrong reserved words -> correct
WRONG_RESERVED: dict[str, str] = {
    "n/a": "not applicable",
    "na": "not available",
    "N/A": "not applicable",
    "NA": "not available",
    "unknown": "not available",
    "null": "not available",
    "none": "not available",
    "-": "not available",
}


def get_ontologies_for_column(inner_name: str) -> list[str]:
    """Return expected ontology prefixes for a column name."""
    return COLUMN_ONTOLOGY_MAP.get(inner_name.lower(), [])


def try_load_terms_tsv(spec_path: str | Path = "spec/sdrf-proteomics/TERMS.tsv") -> dict[str, list[str]] | None:
    """Try to load column-ontology mappings from TERMS.tsv.

    Returns a dict mapping column inner name -> list of ontology prefixes,
    or None if the file is not available.
    """
    path = Path(spec_path)
    if not path.exists():
        return None

    import csv
    result: dict[str, list[str]] = {}
    with path.open(encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            name = row.get("name", "").strip()
            values = row.get("values", "").strip()
            if name and values:
                ontologies = [v.strip() for v in values.split(",") if v.strip()]
                result[name.lower()] = ontologies
    return result
