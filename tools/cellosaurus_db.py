"""Cellosaurus full database lookup tool.

Provides offline lookup from the complete cellosaurus-all-celllines.tsv
database, including all ontology accessions (CLO, BTO, EFO, NCIT, MONDO, UBERON, CL).

Supports both the standalone CLI (python -m tools.cellosaurus_db lookup <name>)
and integration with the unified tools/cli.py.
"""

from __future__ import annotations

import csv
import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Database schema (matches cellosaurus-all-celllines.tsv columns)
# ---------------------------------------------------------------------------

CELLOSAURUS_DB_COLUMNS = [
    "cell line",
    "cellosaurus name",
    "cellosaurus accession",
    "cell_line_clo",
    "clo_accession_cell_line",
    "cell_line_bto",
    "bto_accession_cell_line",
    "cell_line_efo",
    "efo_accession_cell_line",
    "organism",
    "organism_accession",
    "organism part",
    "uberon_accession_organism_part",
    "bto_organism_part",
    "bto_accession_organism_part",
    "sampling site",
    "uberon_accession_sampling_site",
    "age",
    "developmental stage",
    "sex",
    "ancestry category",
    "disease",
    "disease_ncit_accession",
    "disease_mondo_accession",
    "disease_efo_accession",
    "cell type",
    "cell_type_accession",
    "Material type",
    "synonyms_by_cellosaurus",
    "synonyms",
    "curated",
]

# Columns to display in lookup output
LOOKUP_DISPLAY_COLUMNS = [
    "cell line",
    "cellosaurus accession",
    "organism",
    "organism_accession",
    "organism part",
    "uberon_accession_organism_part",
    "sampling site",
    "uberon_accession_sampling_site",
    "age",
    "developmental stage",
    "sex",
    "ancestry category",
    "disease",
    "disease_ncit_accession",
    "disease_mondo_accession",
    "disease_efo_accession",
    "cell type",
    "cell_type_accession",
    "cell_line_clo",
    "clo_accession_cell_line",
    "cell_line_bto",
    "bto_accession_cell_line",
    "cell_line_efo",
    "efo_accession_cell_line",
    "synonyms_by_cellosaurus",
    "synonyms",
]

# Default data directory
_DATA_DIR = Path(__file__).parent.parent / "data"
DEFAULT_CELLOSAURUS_PATH = _DATA_DIR / "cellosaurus-all-celllines.tsv"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CellosaurusEntry:
    """A single cell line record from the full Cellosaurus database."""
    cell_line: str = "not available"
    cellosaurus_name: str = "not available"
    cellosaurus_accession: str = "not available"
    cell_line_clo: str = "not available"
    clo_accession_cell_line: str = "not available"
    cell_line_bto: str = "not available"
    bto_accession_cell_line: str = "not available"
    cell_line_efo: str = "not available"
    efo_accession_cell_line: str = "not available"
    organism: str = "not available"
    organism_accession: str = "not available"
    organism_part: str = "not available"
    uberon_accession_organism_part: str = "not available"
    bto_organism_part: str = "not available"
    bto_accession_organism_part: str = "not available"
    sampling_site: str = "not available"
    uberon_accession_sampling_site: str = "not available"
    age: str = "not available"
    developmental_stage: str = "not available"
    sex: str = "not available"
    ancestry_category: str = "not available"
    disease: str = "not available"
    disease_ncit_accession: str = "not available"
    disease_mondo_accession: str = "not available"
    disease_efo_accession: str = "not available"
    cell_type: str = "not available"
    cell_type_accession: str = "not available"
    material_type: str = "not available"
    synonyms_by_cellosaurus: list[str] = field(default_factory=list)
    synonyms: list[str] = field(default_factory=list)
    curated: str = "not curated"

    @classmethod
    def from_row(cls, row: dict[str, str]) -> CellosaurusEntry:
        """Create from a TSV row dict."""
        def _split(val: str) -> list[str]:
            if not val or val == "not available":
                return []
            return [s.strip() for s in val.split(";") if s.strip()]

        def _get(key: str, default: str = "not available") -> str:
            return row.get(key, default).strip()

        return cls(
            cell_line=_get("cell line"),
            cellosaurus_name=_get("cellosaurus name"),
            cellosaurus_accession=_get("cellosaurus accession"),
            cell_line_clo=_get("cell_line_clo"),
            clo_accession_cell_line=_get("clo_accession_cell_line"),
            cell_line_bto=_get("cell_line_bto"),
            bto_accession_cell_line=_get("bto_accession_cell_line"),
            cell_line_efo=_get("cell_line_efo"),
            efo_accession_cell_line=_get("efo_accession_cell_line"),
            organism=_get("organism"),
            organism_accession=_get("organism_accession"),
            organism_part=_get("organism part"),
            uberon_accession_organism_part=_get("uberon_accession_organism_part"),
            bto_organism_part=_get("bto_organism_part"),
            bto_accession_organism_part=_get("bto_accession_organism_part"),
            sampling_site=_get("sampling site"),
            uberon_accession_sampling_site=_get("uberon_accession_sampling_site"),
            age=_get("age"),
            developmental_stage=_get("developmental stage"),
            sex=_get("sex"),
            ancestry_category=_get("ancestry category"),
            disease=_get("disease"),
            disease_ncit_accession=_get("disease_ncit_accession"),
            disease_mondo_accession=_get("disease_mondo_accession"),
            disease_efo_accession=_get("disease_efo_accession"),
            cell_type=_get("cell type"),
            cell_type_accession=_get("cell_type_accession"),
            material_type=_get("Material type", "not available"),
            synonyms_by_cellosaurus=_split(_get("synonyms_by_cellosaurus")),
            synonyms=_split(_get("synonyms")),
            curated=_get("curated"),
        )

    def all_names(self) -> list[str]:
        """Return all known names for this cell line (for matching)."""
        names = []
        if self.cell_line and self.cell_line != "not available":
            names.append(self.cell_line)
        if self.cellosaurus_name and self.cellosaurus_name != "not available":
            names.append(self.cellosaurus_name)
        if self.cellosaurus_accession and self.cellosaurus_accession != "not available":
            names.append(self.cellosaurus_accession)
        names.extend(self.synonyms_by_cellosaurus)
        names.extend(self.synonyms)
        return names

    def get_field(self, field_name: str) -> str:
        """Get a field value by name."""
        return getattr(self, field_name, "not available")

    def to_display_dict(self) -> dict[str, str]:
        """Return all fields as a dict for display."""
        result = {}
        for col in CELLOSAURUS_DB_COLUMNS:
            val = getattr(self, col.replace(" ", "_").replace("-", "_"), "not available")
            if isinstance(val, list):
                val = "; ".join(val) if val else "not available"
            result[col] = val
        return result


@dataclass
class CellosaurusMatchResult:
    """Result of looking up a cell line in Cellosaurus."""
    query: str
    entry: CellosaurusEntry | None
    match_type: str = ""  # "exact", "synonym", "fuzzy", "none"
    confidence: float = 0.0
    matched_name: str = ""


# ---------------------------------------------------------------------------
# Database class
# ---------------------------------------------------------------------------

class CellosaurusDatabase:
    """In-memory Cellosaurus cell line metadata database."""

    def __init__(self):
        self.entries: dict[str, CellosaurusEntry] = {}  # keyed by cellosaurus accession
        self._name_index: dict[str, str] = {}  # normalized name -> accession key
        self._accession_index: dict[str, str] = {}  # accession -> accession key
        self._all_names: list[str] = []  # all normalized names for fuzzy matching

    def load(self, db_path: str | Path = DEFAULT_CELLOSAURUS_PATH) -> None:
        """Load the Cellosaurus database from TSV file."""
        db_path = Path(db_path)
        if not db_path.exists():
            raise FileNotFoundError(
                f"Cellosaurus database not found: {db_path}\n"
                "Please ensure cellosaurus-all-celllines.tsv exists in the data directory."
            )

        loaded = 0
        with db_path.open(encoding="utf-8-sig") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                entry = CellosaurusEntry.from_row(row)
                accession = entry.cellosaurus_accession
                if not accession or accession == "not available":
                    continue
                self.entries[accession] = entry
                # Index by accession
                self._accession_index[accession.lower()] = accession
                # Index all names
                for name in entry.all_names():
                    norm = self._normalize(name)
                    if norm:
                        self._name_index[norm] = accession

                loaded += 1

        self._all_names = list(self._name_index.keys())

    @staticmethod
    def _normalize(name: str) -> str:
        """Normalize a cell line name for matching."""
        if not name or name == "not available":
            return ""
        return re.sub(r"[\s\-_().]+", "", name.strip().lower())

    @property
    def size(self) -> int:
        return len(self.entries)

    def find(self, query: str) -> CellosaurusMatchResult:
        """Look up a cell line by name, accession, or synonym.

        Tries in order: exact accession match, exact name match, synonym match, fuzzy match.
        """
        if not query or query.lower() in ("not available", "not applicable"):
            return CellosaurusMatchResult(query=query, entry=None, match_type="none")

        norm = self._normalize(query)
        if not norm:
            return CellosaurusMatchResult(query=query, entry=None, match_type="none")

        # 1. Exact accession match
        if query.lower() in self._accession_index:
            accession = self._accession_index[query.lower()]
            return CellosaurusMatchResult(
                query=query,
                entry=self.entries[accession],
                match_type="exact",
                confidence=1.0,
                matched_name=accession,
            )

        # 2. Exact name match
        if norm in self._name_index:
            accession = self._name_index[norm]
            entry = self.entries[accession]
            return CellosaurusMatchResult(
                query=query,
                entry=entry,
                match_type="exact",
                confidence=1.0,
                matched_name=entry.cell_line or entry.cellosaurus_name or accession,
            )

        # 3. Substring match in synonyms
        if len(norm) >= 4:
            for key, entry in self.entries.items():
                for syn in entry.synonyms_by_cellosaurus + entry.synonyms:
                    norm_syn = self._normalize(syn)
                    if norm_syn and len(norm_syn) >= 4:
                        if norm == norm_syn or norm.startswith(norm_syn) or norm_syn.startswith(norm):
                            return CellosaurusMatchResult(
                                query=query,
                                entry=entry,
                                match_type="synonym",
                                confidence=0.9,
                                matched_name=entry.cell_line or entry.cellosaurus_name or key,
                            )

        # 4. Fuzzy match using difflib
        close = difflib.get_close_matches(norm, self._all_names, n=1, cutoff=0.75)
        if close:
            accession = self._name_index[close[0]]
            entry = self.entries[accession]
            ratio = difflib.SequenceMatcher(None, norm, close[0]).ratio()
            return CellosaurusMatchResult(
                query=query,
                entry=entry,
                match_type="fuzzy",
                confidence=ratio,
                matched_name=entry.cell_line or entry.cellosaurus_name or accession,
            )

        return CellosaurusMatchResult(query=query, entry=None, match_type="none")

    def find_all(self, queries: list[str]) -> list[CellosaurusMatchResult]:
        """Look up multiple cell lines. Caches results for repeated queries."""
        cache: dict[str, CellosaurusMatchResult] = {}
        results = []
        for q in queries:
            norm = self._normalize(q)
            if norm not in cache:
                cache[norm] = self.find(q)
            cached = cache[norm]
            results.append(CellosaurusMatchResult(
                query=q,
                entry=cached.entry,
                match_type=cached.match_type,
                confidence=cached.confidence,
                matched_name=cached.matched_name,
            ))
        return results


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def format_entry_display(entry: CellosaurusEntry, match: CellosaurusMatchResult) -> str:
    """Format a cell line entry for display."""
    lines = []
    lines.append(f"Cell line: {entry.cell_line if entry.cell_line != 'not available' else '(not available)'}")
    lines.append(f"Match: {match.match_type} (confidence: {match.confidence:.2f})")
    lines.append(f"Cellosaurus accession: {entry.cellosaurus_accession}")

    if entry.organism != "not available":
        lines.append(f"Organism: {entry.organism}")
        if entry.organism_accession != "not available":
            lines.append(f"  Accession: {entry.organism_accession}")

    if entry.organism_part != "not available":
        lines.append(f"Organ/tissue: {entry.organism_part}")
        for label, acc in [
            ("UBERON", entry.uberon_accession_organism_part),
            ("BTO", entry.bto_accession_organism_part),
        ]:
            if acc != "not available":
                lines.append(f"  {label}: {acc}")

    if entry.sampling_site != "not available":
        lines.append(f"Sampling site: {entry.sampling_site}")
        if entry.uberon_accession_sampling_site != "not available":
            lines.append(f"  UBERON: {entry.uberon_accession_sampling_site}")

    if entry.disease != "not available":
        lines.append(f"Disease: {entry.disease}")
        for label, acc in [
            ("NCIT", entry.disease_ncit_accession),
            ("MONDO", entry.disease_mondo_accession),
            ("EFO", entry.disease_efo_accession),
        ]:
            if acc != "not available":
                lines.append(f"  {label}: {acc}")

    if entry.cell_type != "not available":
        lines.append(f"Cell type: {entry.cell_type}")
        if entry.cell_type_accession != "not available":
            lines.append(f"  CL: {entry.cell_type_accession}")

    if entry.age != "not available":
        lines.append(f"Age: {entry.age}")
    if entry.developmental_stage != "not available":
        lines.append(f"Developmental stage: {entry.developmental_stage}")
    if entry.sex != "not available":
        lines.append(f"Sex: {entry.sex}")
    if entry.ancestry_category != "not available":
        lines.append(f"Ancestry: {entry.ancestry_category}")

    if entry.cell_line_clo != "not available":
        lines.append(f"CLO: {entry.cell_line_clo}")
        if entry.clo_accession_cell_line != "not available":
            lines.append(f"  CLO accession: {entry.clo_accession_cell_line}")
    if entry.cell_line_bto != "not available":
        lines.append(f"BTO: {entry.cell_line_bto}")
        if entry.bto_accession_cell_line != "not available":
            lines.append(f"  BTO accession: {entry.bto_accession_cell_line}")
    if entry.cell_line_efo != "not available":
        lines.append(f"EFO: {entry.cell_line_efo}")
        if entry.efo_accession_cell_line != "not available":
            lines.append(f"  EFO accession: {entry.efo_accession_cell_line}")

    if entry.synonyms_by_cellosaurus:
        lines.append(f"Synonyms (Cellosaurus): {'; '.join(entry.synonyms_by_cellosaurus[:15])}")
    if entry.synonyms:
        lines.append(f"Synonyms: {'; '.join(entry.synonyms[:15])}")

    if entry.curated != "not available":
        lines.append(f"Curated: {entry.curated}")

    return "\n".join(lines)


def format_entry_tsv(entry: CellosaurusEntry) -> str:
    """Format a cell line entry as a TSV row."""
    values = []
    for col in CELLOSAURUS_DB_COLUMNS:
        val = getattr(entry, col.replace(" ", "_").replace("-", "_"), "not available")
        if isinstance(val, list):
            val = "; ".join(val) if val else "not available"
        values.append(val)
    return "\t".join(values)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """CLI entry point for Cellosaurus database tools."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Full Cellosaurus database lookup — all ontology accessions included"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # lookup
    p = sub.add_parser("lookup", help="Look up a cell line in the Cellosaurus database")
    p.add_argument("name", help="Cell line name, accession (e.g. HeLa, CVCL_0030, CVCL_0030)")
    p.add_argument("--db", default=str(DEFAULT_CELLOSAURUS_PATH), help="Path to cellosaurus TSV")
    p.add_argument("--format", choices=["text", "tsv"], default="text",
                   help="Output format (default: text)")
    p.add_argument("--all", action="store_true",
                   help="Show all matches (for fuzzy/search mode)")

    # stats
    p = sub.add_parser("stats", help="Show database statistics")
    p.add_argument("--db", default=str(DEFAULT_CELLOSAURUS_PATH), help="Path to cellosaurus TSV")

    # search
    p = sub.add_parser("search", help="Search cell lines by keyword (fuzzy)")
    p.add_argument("keyword", help="Keyword to search for")
    p.add_argument("--db", default=str(DEFAULT_CELLOSAURUS_PATH), help="Path to cellosaurus TSV")
    p.add_argument("--limit", type=int, default=10, help="Max results to show")

    args = parser.parse_args(argv)

    if args.command == "lookup":
        db = CellosaurusDatabase()
        db.load(args.db)
        result = db.find(args.name)
        if result.entry:
            if args.format == "tsv":
                print(format_entry_tsv(result.entry))
            else:
                print(format_entry_display(result.entry, result))
        else:
            print(f"Cell line '{args.name}' not found in database")
            return 1

    elif args.command == "stats":
        db = CellosaurusDatabase()
        db.load(args.db)
        organisms: dict[str, int] = {}
        diseases: dict[str, int] = {}
        for entry in db.entries.values():
            org = entry.organism
            if org and org != "not available":
                organisms[org] = organisms.get(org, 0) + 1
            dis = entry.disease
            if dis and dis != "not available":
                diseases[dis] = diseases.get(dis, 0) + 1

        print("Cellosaurus Database Statistics")
        print(f"  Total entries: {db.size}")
        print(f"  Name index: {len(db._name_index)} names")
        print("\n  Organisms:")
        for org, count in sorted(organisms.items(), key=lambda x: -x[1])[:10]:
            print(f"    {org}: {count}")
        print(f"\n  Total diseases: {len(diseases)}")
        print(f"  Top diseases:")
        for dis, count in sorted(diseases.items(), key=lambda x: -x[1])[:5]:
            print(f"    {dis}: {count}")

    elif args.command == "search":
        db = CellosaurusDatabase()
        db.load(args.db)
        results = []
        # Try fuzzy search on all entries
        for accession, entry in db.entries.items():
            match_name = entry.cell_line or entry.cellosaurus_name or ""
            norm = db._normalize(match_name)
            if db._normalize(args.keyword) in norm or norm in db._normalize(args.keyword):
                ratio = difflib.SequenceMatcher(None, db._normalize(args.keyword), norm).ratio()
                results.append((ratio, entry))
            else:
                # Check synonyms
                for syn in entry.synonyms + entry.synonyms_by_cellosaurus:
                    norm_syn = db._normalize(syn)
                    if db._normalize(args.keyword) in norm_syn or norm_syn in db._normalize(args.keyword):
                        ratio = difflib.SequenceMatcher(None, db._normalize(args.keyword), norm_syn).ratio()
                        results.append((ratio, entry))
                        break

        # Sort by confidence and deduplicate
        seen = set()
        unique_results = []
        for ratio, entry in sorted(results, key=lambda x: -x[0]):
            acc = entry.cellosaurus_accession
            if acc not in seen:
                seen.add(acc)
                unique_results.append((ratio, entry))

        if not unique_results:
            print(f"No results found for '{args.keyword}'")
            return 1

        print(f"Found {len(unique_results)} results for '{args.keyword}':\n")
        for ratio, entry in unique_results[:args.limit]:
            accession = entry.cellosaurus_accession
            name = entry.cell_line if entry.cell_line != "not available" else entry.cellosaurus_name
            disease = entry.disease if entry.disease != "not available" else ""
            print(f"  {name} ({accession})")
            print(f"    Organism: {entry.organism}")
            if disease:
                print(f"    Disease: {disease}")
            print(f"    Match confidence: {ratio:.2f}")
            print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
