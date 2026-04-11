"""Tests for tools.cellline_db — cell line metadata database."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.cellline_db import (
    CellLineDatabase,
    CellLineEntry,
    MatchResult,
    annotate_sdrf_celllines,
    estimate_developmental_stage,
    DEFAULT_DB_PATH,
)


# ---------------------------------------------------------------------------
# Skip if database not available
# ---------------------------------------------------------------------------

DB_AVAILABLE = DEFAULT_DB_PATH.exists()
skip_no_db = pytest.mark.skipif(not DB_AVAILABLE, reason="Cell line database not found")


# ---------------------------------------------------------------------------
# Unit tests (no database needed)
# ---------------------------------------------------------------------------

class TestCellLineEntry:
    def test_from_row(self):
        row = {
            "cell line": "HeLa",
            "cellosaurus name": "HeLa",
            "cellosaurus accession": "CVCL_0030",
            "bto cell line": "HeLa cell",
            "organism": "Homo sapiens",
            "organism part": "Cervix",
            "sampling site": "Cervix",
            "age": "31Y",
            "developmental stage": "Adult",
            "sex": "Female",
            "ancestry category": "African American",
            "disease": "Cervical adenocarcinoma",
            "cell type": "epithelial",
            "Material type": "cell",
            "synonyms": "HELA; HeLa S3; HeLa-S3",
            "curated": "curated",
        }
        entry = CellLineEntry.from_row(row)
        assert entry.cell_line == "HeLa"
        assert entry.cellosaurus_accession == "CVCL_0030"
        assert entry.organism == "Homo sapiens"
        assert len(entry.synonyms) == 3
        assert "HELA" in entry.synonyms

    def test_all_names(self):
        entry = CellLineEntry(
            cell_line="MCF-7",
            cellosaurus_name="MCF-7",
            cellosaurus_accession="CVCL_0031",
            synonyms=["MCF7", "BR_MCF7"],
        )
        names = entry.all_names()
        assert "MCF-7" in names
        assert "CVCL_0031" in names
        assert "MCF7" in names

    def test_enrichment_dict(self):
        entry = CellLineEntry(
            cell_line="A549",
            organism="Homo sapiens",
            disease="Lung carcinoma",
        )
        d = entry.to_enrichment_dict()
        assert d["organism"] == "Homo sapiens"
        assert d["disease"] == "Lung carcinoma"
        assert "cell line" not in d  # not in enrichment


class TestDevelopmentalStage:
    def test_infant(self):
        assert estimate_developmental_stage("1Y") == "Infant"

    def test_children(self):
        assert estimate_developmental_stage("5Y") == "Children"

    def test_adult(self):
        assert estimate_developmental_stage("30Y") == "Adult"

    def test_elderly(self):
        assert estimate_developmental_stage("70Y") == "Elderly"

    def test_not_available(self):
        assert estimate_developmental_stage("not available") == "not available"


# ---------------------------------------------------------------------------
# Database tests (require data/cl-annotations-db.tsv)
# ---------------------------------------------------------------------------

@skip_no_db
class TestCellLineDatabase:
    @pytest.fixture
    def db(self) -> CellLineDatabase:
        db = CellLineDatabase()
        db.load()
        return db

    def test_load_size(self, db: CellLineDatabase):
        assert db.size > 100  # should have many cell lines

    def test_exact_match_hela(self, db: CellLineDatabase):
        result = db.find("HeLa")
        assert result.entry is not None
        assert result.match_type == "exact"
        assert result.confidence == 1.0
        assert "Homo" in result.entry.organism

    def test_exact_match_case_insensitive(self, db: CellLineDatabase):
        result = db.find("hela")
        assert result.entry is not None
        assert result.match_type == "exact"

    def test_exact_match_mcf7(self, db: CellLineDatabase):
        result = db.find("MCF-7")
        assert result.entry is not None

    def test_exact_match_a549(self, db: CellLineDatabase):
        result = db.find("A549")
        assert result.entry is not None

    def test_accession_match(self, db: CellLineDatabase):
        result = db.find("CVCL_0002")
        assert result.entry is not None
        assert result.match_type == "exact"

    def test_synonym_match(self, db: CellLineDatabase):
        result = db.find("HL60")
        assert result.entry is not None
        # Should match HL-60

    def test_not_found(self, db: CellLineDatabase):
        result = db.find("COMPLETELY_FAKE_CELLLINE_12345")
        assert result.entry is None
        assert result.match_type == "none"

    def test_not_available_skipped(self, db: CellLineDatabase):
        result = db.find("not available")
        assert result.entry is None
        assert result.match_type == "none"

    def test_find_all(self, db: CellLineDatabase):
        results = db.find_all(["HeLa", "MCF-7", "FAKE"])
        assert len(results) == 3
        assert results[0].entry is not None
        assert results[1].entry is not None
        assert results[2].entry is None


@skip_no_db
class TestAnnotateSdrfCelllines:
    def test_annotate_with_cell_line_column(self):
        content = (
            "source name\tcharacteristics[cell line]\tassay name\n"
            "s1\tHeLa\trun1\n"
            "s2\tMCF-7\trun2\n"
            "s3\tFAKELINE\trun3\n"
        )
        enriched, report = annotate_sdrf_celllines(content)
        assert report.total_rows == 3
        assert report.matched >= 2
        assert report.unmatched <= 1
        assert "suggested[organism]" in enriched
        assert "match_type" in enriched

    def test_annotate_without_cell_line_column(self):
        content = (
            "source name\tcharacteristics[organism]\tassay name\n"
            "s1\tHomo sapiens\trun1\n"
        )
        enriched, report = annotate_sdrf_celllines(content)
        assert report.unmatched == report.total_rows

    def test_report_summary(self):
        content = (
            "source name\tcharacteristics[cell line]\tassay name\n"
            "s1\tHeLa\trun1\n"
        )
        enriched, report = annotate_sdrf_celllines(content)
        summary = report.summary()
        assert "Cell Line Annotation Report" in summary
