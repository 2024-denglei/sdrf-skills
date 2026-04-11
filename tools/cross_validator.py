"""Multi-AI cross-validation framework for SDRF annotation.

Sends the same annotation task to multiple AI models and compares outputs.
Supports Claude, OpenAI, and Gemini backends with consensus building.
"""

from __future__ import annotations

import json
import os
import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tools.completeness import QualityReport, score_sdrf
from tools.hallucination import HallucinationReport, detect_hallucinations
from tools.sdrf_parser import parse_sdrf, SDRFFile


# ---------------------------------------------------------------------------
# Annotation prompt template
# ---------------------------------------------------------------------------

ANNOTATION_PROMPT = """You are an expert SDRF (Sample and Data Relationship Format) annotator for proteomics.

Given the following project metadata, produce a valid SDRF TSV file.

## Project Info
{project_info}

## Rules
1. Use ontology accessions from: NCBITaxon (organism), MONDO/EFO (disease),
   UBERON (tissue), CL (cell type), MS (instrument), UNIMOD (modifications)
2. Modification format: NT=name;AC=UNIMOD:id;TA=amino_acid;MT=Fixed|Variable
3. Instrument format: AC=MS:accession;NT=instrument_name
4. Reserved words: "not available", "not applicable" (never "N/A", "NA")
5. CRITICAL: UNIMOD:1 = Acetyl, UNIMOD:21 = Phospho (do NOT swap)
6. Sex values must be lowercase ("male", "female")
7. Age format: number + unit suffix (e.g., "58Y", "6M")

## Output
Produce ONLY the SDRF as tab-separated values. No explanation, no markdown fences.
Start with the header row.
"""


# ---------------------------------------------------------------------------
# Annotator backends
# ---------------------------------------------------------------------------

@dataclass
class AnnotationResult:
    """Output from a single AI annotator."""
    annotator_name: str
    sdrf_content: str
    raw_response: str = ""
    error: str | None = None


class Annotator(ABC):
    """Base class for AI annotator backends."""

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def annotate(self, project_info: str) -> AnnotationResult:
        ...


class ClaudeAnnotator(Annotator):
    """Annotator using the Anthropic Claude API."""

    def __init__(self, model: str = "claude-sonnet-4-20250514", api_key: str | None = None):
        self.model = model
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")

    @property
    def name(self) -> str:
        return f"claude:{self.model}"

    def annotate(self, project_info: str) -> AnnotationResult:
        if not self.api_key:
            return AnnotationResult(
                annotator_name=self.name,
                sdrf_content="",
                error="ANTHROPIC_API_KEY not set",
            )
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=self.api_key)
            response = client.messages.create(
                model=self.model,
                max_tokens=4096,
                messages=[{
                    "role": "user",
                    "content": ANNOTATION_PROMPT.format(project_info=project_info),
                }],
            )
            text = response.content[0].text
            return AnnotationResult(
                annotator_name=self.name,
                sdrf_content=_extract_tsv(text),
                raw_response=text,
            )
        except Exception as e:
            return AnnotationResult(
                annotator_name=self.name,
                sdrf_content="",
                error=str(e),
            )


class OpenAIAnnotator(Annotator):
    """Annotator using the OpenAI API."""

    def __init__(self, model: str = "gpt-4o", api_key: str | None = None):
        self.model = model
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")

    @property
    def name(self) -> str:
        return f"openai:{self.model}"

    def annotate(self, project_info: str) -> AnnotationResult:
        if not self.api_key:
            return AnnotationResult(
                annotator_name=self.name,
                sdrf_content="",
                error="OPENAI_API_KEY not set",
            )
        try:
            import openai
            client = openai.OpenAI(api_key=self.api_key)
            response = client.chat.completions.create(
                model=self.model,
                messages=[{
                    "role": "user",
                    "content": ANNOTATION_PROMPT.format(project_info=project_info),
                }],
                max_tokens=4096,
            )
            text = response.choices[0].message.content or ""
            return AnnotationResult(
                annotator_name=self.name,
                sdrf_content=_extract_tsv(text),
                raw_response=text,
            )
        except Exception as e:
            return AnnotationResult(
                annotator_name=self.name,
                sdrf_content="",
                error=str(e),
            )


class GeminiAnnotator(Annotator):
    """Annotator using the Google Gemini API."""

    def __init__(self, model: str = "gemini-2.5-flash", api_key: str | None = None):
        self.model = model
        self.api_key = api_key or os.environ.get("GOOGLE_API_KEY", "")

    @property
    def name(self) -> str:
        return f"gemini:{self.model}"

    def annotate(self, project_info: str) -> AnnotationResult:
        if not self.api_key:
            return AnnotationResult(
                annotator_name=self.name,
                sdrf_content="",
                error="GOOGLE_API_KEY not set",
            )
        try:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            model = genai.GenerativeModel(self.model)
            response = model.generate_content(
                ANNOTATION_PROMPT.format(project_info=project_info)
            )
            text = response.text
            return AnnotationResult(
                annotator_name=self.name,
                sdrf_content=_extract_tsv(text),
                raw_response=text,
            )
        except Exception as e:
            return AnnotationResult(
                annotator_name=self.name,
                sdrf_content="",
                error=str(e),
            )


class DeterministicAnnotator(Annotator):
    """Non-AI annotator that uses tools programmatically. Serves as baseline."""

    @property
    def name(self) -> str:
        return "deterministic"

    def annotate(self, project_info: str) -> AnnotationResult:
        # This is a stub — in practice it would fetch PRIDE metadata
        # and construct SDRF using known values and OLS lookups.
        return AnnotationResult(
            annotator_name=self.name,
            sdrf_content="",
            error="Deterministic annotator requires PRIDE + OLS integration",
        )


# ---------------------------------------------------------------------------
# Consensus data structures
# ---------------------------------------------------------------------------

@dataclass
class ConsensusTerm:
    """A term agreed upon by multiple annotators."""
    column: str
    value: str
    accession: str
    agreed_by: list[str]  # annotator names


@dataclass
class DisputedTerm:
    """A term where annotators disagree."""
    column: str
    variants: dict[str, str]  # annotator_name -> value
    resolved_value: str | None = None
    resolution_method: str = ""


@dataclass
class CrossValidationReport:
    """Full report from multi-AI cross-validation."""
    project_info: str
    annotators_used: list[str] = field(default_factory=list)
    results: list[AnnotationResult] = field(default_factory=list)
    per_annotator_quality: dict[str, QualityReport] = field(default_factory=dict)
    per_annotator_hallucinations: dict[str, HallucinationReport] = field(default_factory=dict)
    consensus_terms: list[ConsensusTerm] = field(default_factory=list)
    disputed_terms: list[DisputedTerm] = field(default_factory=list)
    consensus_sdrf: str = ""

    def summary(self) -> str:
        lines = [
            "Cross-Validation Report",
            f"  Annotators: {', '.join(self.annotators_used)}",
            f"  Successful: {sum(1 for r in self.results if not r.error)}/{len(self.results)}",
        ]

        for name, quality in self.per_annotator_quality.items():
            halluc = self.per_annotator_hallucinations.get(name)
            h_count = halluc.total_issues if halluc else "?"
            lines.append(f"  {name}: quality={quality.overall:.0f}/100, issues={h_count}")

        lines.append(f"  Consensus terms: {len(self.consensus_terms)}")
        lines.append(f"  Disputed terms: {len(self.disputed_terms)}")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Cross-validation engine
# ---------------------------------------------------------------------------

class CrossValidator:
    """Orchestrates multi-AI cross-validation of SDRF annotations."""

    def __init__(
        self,
        annotators: list[Annotator] | None = None,
        cache_dir: str | Path | None = None,
    ):
        self.annotators = annotators or [
            ClaudeAnnotator(),
            OpenAIAnnotator(),
            GeminiAnnotator(),
        ]
        self.cache_dir = Path(cache_dir) if cache_dir else None

    def cross_validate(self, project_info: str) -> CrossValidationReport:
        """Run annotation with all annotators and compare results."""
        report = CrossValidationReport(project_info=project_info)
        report.annotators_used = [a.name for a in self.annotators]

        # Collect annotations
        for annotator in self.annotators:
            result = self._get_or_run(annotator, project_info)
            report.results.append(result)

        # Analyze each successful annotation
        successful = [r for r in report.results if not r.error and r.sdrf_content.strip()]
        for result in successful:
            try:
                quality = score_sdrf(result.sdrf_content)
                report.per_annotator_quality[result.annotator_name] = quality
            except Exception:
                pass

            try:
                hallucination = detect_hallucinations(
                    result.sdrf_content, verify_online=False
                )
                report.per_annotator_hallucinations[result.annotator_name] = hallucination
            except Exception:
                pass

        # Build consensus
        if len(successful) >= 2:
            self._build_consensus(successful, report)

        return report

    def _get_or_run(
        self, annotator: Annotator, project_info: str
    ) -> AnnotationResult:
        """Run annotator, optionally caching results."""
        if self.cache_dir:
            cache_key = hashlib.md5(
                f"{annotator.name}:{project_info}".encode()
            ).hexdigest()
            cache_file = self.cache_dir / f"{cache_key}.json"

            if cache_file.exists():
                data = json.loads(cache_file.read_text())
                return AnnotationResult(**data)

            result = annotator.annotate(project_info)

            if not result.error:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(json.dumps({
                    "annotator_name": result.annotator_name,
                    "sdrf_content": result.sdrf_content,
                    "raw_response": result.raw_response,
                    "error": result.error,
                }))
            return result

        return annotator.annotate(project_info)

    def _build_consensus(
        self,
        results: list[AnnotationResult],
        report: CrossValidationReport,
    ) -> None:
        """Compare annotations and build consensus."""
        sdrfs = []
        for r in results:
            try:
                sdrfs.append((r.annotator_name, parse_sdrf(r.sdrf_content)))
            except Exception:
                continue

        if len(sdrfs) < 2:
            return

        # Collect all column names across annotators
        all_columns: set[str] = set()
        for name, sdrf in sdrfs:
            for col in sdrf.columns:
                all_columns.add(col.raw_name.lower())

        # For each column, compare values across annotators
        for col_name in sorted(all_columns):
            values_by_annotator: dict[str, set[str]] = {}
            for ann_name, sdrf in sdrfs:
                for i, col in enumerate(sdrf.columns):
                    if col.raw_name.lower() == col_name:
                        key = sdrf.key_for_column(i)
                        vals = sdrf.unique_values(key)
                        values_by_annotator[ann_name] = vals
                        break

            if not values_by_annotator:
                continue

            # Find common values
            all_vals = set()
            for vals in values_by_annotator.values():
                all_vals.update(vals)

            for val in all_vals:
                agreeing = [
                    name for name, vals in values_by_annotator.items()
                    if val in vals
                ]
                if len(agreeing) == len(values_by_annotator):
                    report.consensus_terms.append(ConsensusTerm(
                        column=col_name,
                        value=val,
                        accession="",
                        agreed_by=agreeing,
                    ))
                elif len(agreeing) >= 2 and len(agreeing) >= len(values_by_annotator) * 0.5:
                    # Majority agreement
                    report.consensus_terms.append(ConsensusTerm(
                        column=col_name,
                        value=val,
                        accession="",
                        agreed_by=agreeing,
                    ))
                else:
                    # Disputed
                    variants = {}
                    for name, vals in values_by_annotator.items():
                        if val in vals:
                            variants[name] = val
                        else:
                            # Get what this annotator used instead
                            other_vals = vals - {val}
                            if other_vals:
                                variants[name] = next(iter(other_vals))
                    if len(variants) >= 2:
                        report.disputed_terms.append(DisputedTerm(
                            column=col_name,
                            variants=variants,
                        ))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_tsv(text: str) -> str:
    """Extract TSV content from a model response that may have markdown fences."""
    lines = text.strip().split("\n")

    # Strip markdown code fences
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]

    # Find the header line (should contain "source name")
    start = 0
    for i, line in enumerate(lines):
        if "source name" in line.lower():
            start = i
            break

    return "\n".join(lines[start:])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Cross-validate SDRF annotations across multiple AI models"
    )
    parser.add_argument("project_info", help="Project description or PXD accession")
    parser.add_argument(
        "--models", default="claude,openai,gemini",
        help="Comma-separated list of models to use",
    )
    parser.add_argument(
        "--cache-dir", default=None,
        help="Directory to cache annotator responses",
    )
    args = parser.parse_args(argv)

    annotators: list[Annotator] = []
    for model in args.models.split(","):
        model = model.strip().lower()
        if model == "claude":
            annotators.append(ClaudeAnnotator())
        elif model == "openai":
            annotators.append(OpenAIAnnotator())
        elif model == "gemini":
            annotators.append(GeminiAnnotator())

    validator = CrossValidator(
        annotators=annotators,
        cache_dir=args.cache_dir,
    )
    report = validator.cross_validate(args.project_info)
    print(report.summary())


if __name__ == "__main__":
    main()
