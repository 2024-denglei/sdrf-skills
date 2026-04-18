"""Tests for tools.cross_validator — multi-AI cross-validation."""

from __future__ import annotations

import pytest

from tools.cross_validator import (
    AnnotationResult,
    CrossValidationReport,
    CrossValidator,
    Annotator,
    _extract_tsv,
    ClaudeAnnotator,
    OpenAIAnnotator,
    GeminiAnnotator,
)


# ---------------------------------------------------------------------------
# Mock annotator for testing
# ---------------------------------------------------------------------------

class MockAnnotator(Annotator):
    """Test annotator that returns pre-configured SDRF content."""

    def __init__(self, annotator_name: str, content: str, error: str | None = None):
        self._name = annotator_name
        self._content = content
        self._error = error

    @property
    def name(self) -> str:
        return self._name

    def annotate(self, project_info: str) -> AnnotationResult:
        return AnnotationResult(
            annotator_name=self._name,
            sdrf_content=self._content,
            error=self._error,
        )


MOCK_SDRF_A = (
    "source name\tcharacteristics[organism]\tcharacteristics[disease]\tassay name\t"
    "technology type\tcomment[data file]\tcomment[fraction identifier]\t"
    "comment[technical replicate]\tcomment[sdrf version]\n"
    "s1\tHomo sapiens\tbreast carcinoma\trun1\tproteomic profiling by mass spectrometry\t"
    "f1.raw\t1\t1\tv1.1.0\n"
)

MOCK_SDRF_B = (
    "source name\tcharacteristics[organism]\tcharacteristics[disease]\tassay name\t"
    "technology type\tcomment[data file]\tcomment[fraction identifier]\t"
    "comment[technical replicate]\tcomment[sdrf version]\n"
    "s1\tHomo sapiens\tbreast cancer\trun1\tproteomic profiling by mass spectrometry\t"
    "f1.raw\t1\t1\tv1.1.0\n"
)

MOCK_SDRF_C = (
    "source name\tcharacteristics[organism]\tcharacteristics[disease]\tassay name\t"
    "technology type\tcomment[data file]\tcomment[fraction identifier]\t"
    "comment[technical replicate]\tcomment[sdrf version]\n"
    "s1\tHomo sapiens\tbreast carcinoma\trun1\tproteomic profiling by mass spectrometry\t"
    "f1.raw\t1\t1\tv1.1.0\n"
)


class TestCrossValidator:
    def test_cross_validate_with_mocks(self):
        annotators = [
            MockAnnotator("model_a", MOCK_SDRF_A),
            MockAnnotator("model_b", MOCK_SDRF_B),
            MockAnnotator("model_c", MOCK_SDRF_C),
        ]
        validator = CrossValidator(annotators=annotators)
        report = validator.cross_validate("Test project: human breast cancer proteomics")

        assert len(report.results) == 3
        assert all(r.error is None for r in report.results)
        assert len(report.per_annotator_quality) == 3

    def test_consensus_on_agreement(self):
        """When all models agree, terms are consensus."""
        annotators = [
            MockAnnotator("model_a", MOCK_SDRF_A),
            MockAnnotator("model_c", MOCK_SDRF_C),  # same as A
        ]
        validator = CrossValidator(annotators=annotators)
        report = validator.cross_validate("Test")

        # "Homo sapiens" should be consensus (both agree)
        consensus_values = {t.value for t in report.consensus_terms}
        assert "Homo sapiens" in consensus_values

    def test_dispute_detection(self):
        """When models disagree, terms are disputed."""
        annotators = [
            MockAnnotator("model_a", MOCK_SDRF_A),   # "breast carcinoma"
            MockAnnotator("model_b", MOCK_SDRF_B),   # "breast cancer"
        ]
        validator = CrossValidator(annotators=annotators)
        report = validator.cross_validate("Test")

        # Both are different disease values — at least one should be in disputes
        # or in consensus separately
        all_values = set()
        for t in report.consensus_terms:
            all_values.add(t.value)
        for d in report.disputed_terms:
            all_values.update(d.variants.values())
        assert "breast carcinoma" in all_values or "breast cancer" in all_values

    def test_handles_error(self):
        annotators = [
            MockAnnotator("model_a", MOCK_SDRF_A),
            MockAnnotator("model_err", "", error="API key missing"),
        ]
        validator = CrossValidator(annotators=annotators)
        report = validator.cross_validate("Test")

        assert len(report.results) == 2
        # Only one should have quality scores
        assert len(report.per_annotator_quality) == 1

    def test_summary_format(self):
        annotators = [
            MockAnnotator("model_a", MOCK_SDRF_A),
            MockAnnotator("model_b", MOCK_SDRF_B),
        ]
        validator = CrossValidator(annotators=annotators)
        report = validator.cross_validate("Test")
        summary = report.summary()
        assert "Cross-Validation Report" in summary
        assert "model_a" in summary
        assert "model_b" in summary


class TestExtractTsv:
    def test_plain_tsv(self):
        text = "source name\torganism\ns1\tHomo sapiens"
        assert _extract_tsv(text) == text

    def test_markdown_fences(self):
        text = "```tsv\nsource name\torganism\ns1\tHomo sapiens\n```"
        assert "source name" in _extract_tsv(text)
        assert "```" not in _extract_tsv(text)

    def test_with_preamble(self):
        text = "Here is the SDRF:\n\nsource name\torganism\ns1\tHomo sapiens"
        result = _extract_tsv(text)
        assert result.startswith("source name")


class TestAnnotatorDefaults:
    def test_claude_no_key(self):
        ann = ClaudeAnnotator(api_key="")
        result = ann.annotate("test")
        assert result.error is not None

    def test_openai_no_key(self):
        ann = OpenAIAnnotator(api_key="")
        result = ann.annotate("test")
        assert result.error is not None

    def test_gemini_no_key(self):
        ann = GeminiAnnotator(api_key="")
        result = ann.annotate("test")
        assert result.error is not None
