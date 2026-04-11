"""Unified CLI entry point for sdrf-skills tools.

Usage:
  python -m tools check <file.sdrf.tsv>          # hallucination check
  python -m tools score <file.sdrf.tsv>           # quality scoring
  python -m tools fix <file.sdrf.tsv> [-o out]    # auto-fix
  python -m tools benchmark <PXD1> <file2> ...    # benchmark suite
  python -m tools crossval <project_info>         # cross-validate
  python -m tools verify <ACCESSION> [--label L]  # verify single term
"""

from __future__ import annotations

import argparse
import sys


def cmd_check(args: argparse.Namespace) -> int:
    from tools.hallucination import detect_hallucinations
    report = detect_hallucinations(
        args.sdrf_file,
        verify_online=not args.offline,
        spec_path=args.spec,
    )
    print(report.summary())

    if report.unimod_swaps:
        print("\nUNIMOD Swaps:")
        for s in report.unimod_swaps:
            print(f"  Row(s) {s.rows}: {s.wrong_accession} -> {s.correct_accession} ({s.correct_name})")

    if report.hallucinated:
        print("\nHallucinated:")
        for h in report.hallucinated:
            print(f"  Row(s) {h.rows}: '{h.label}' in {h.column}")

    if report.mismatched:
        print("\nMismatched:")
        for m in report.mismatched:
            print(f"  Row(s) {m.rows}: expected '{m.expected_label}', got '{m.actual_label}'")

    return 0 if report.is_clean else 1


def cmd_score(args: argparse.Namespace) -> int:
    from tools.completeness import score_sdrf
    report = score_sdrf(args.sdrf_file)
    print(report.summary())
    return 0


def cmd_fix(args: argparse.Namespace) -> int:
    from pathlib import Path
    from tools.sdrf_fixer import fix_sdrf
    fixed, report = fix_sdrf(args.sdrf_file)
    print(report.changelog())
    if args.output:
        Path(args.output).write_text(fixed)
        print(f"\nFixed SDRF written to: {args.output}")
    return 0


def cmd_benchmark(args: argparse.Namespace) -> int:
    from tools.benchmark import BenchmarkSuite
    pxd = [s for s in args.sources if s.upper().startswith("PXD")]
    local = [s for s in args.sources if not s.upper().startswith("PXD")]
    suite = BenchmarkSuite(verify_online=args.online)
    report = suite.run(pxd_accessions=pxd, local_files=local)
    print(report.summary())
    return 0


def cmd_crossval(args: argparse.Namespace) -> int:
    from tools.cross_validator import CrossValidator
    validator = CrossValidator(cache_dir=args.cache_dir)
    report = validator.cross_validate(args.project_info)
    print(report.summary())
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    from tools.ols_client import OLSClient
    client = OLSClient()
    if args.label:
        result = client.verify_accession(args.accession, args.label)
        print(f"Accession: {result.accession}")
        print(f"Exists: {result.exists}")
        print(f"Label match: {result.label_match}")
        if result.resolved_term:
            print(f"OLS label: {result.resolved_term.label}")
            print(f"Ontology: {result.resolved_term.ontology_name}")
        if result.message:
            print(f"Message: {result.message}")
    else:
        term = client.resolve_accession(args.accession)
        if term:
            print(f"Accession: {term.short_form}")
            print(f"Label: {term.label}")
            print(f"Ontology: {term.ontology_name}")
            print(f"Description: {term.description}")
            if term.synonyms:
                print(f"Synonyms: {', '.join(term.synonyms[:5])}")
        else:
            print(f"Accession {args.accession} not found in OLS")
            return 1
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m tools",
        description="SDRF annotation tools — hallucination detection, quality scoring, auto-fixing",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # check
    p = subparsers.add_parser("check", help="Check SDRF for ontology hallucinations")
    p.add_argument("sdrf_file")
    p.add_argument("--offline", action="store_true")
    p.add_argument("--spec", default=None)

    # score
    p = subparsers.add_parser("score", help="Score SDRF quality (0-100)")
    p.add_argument("sdrf_file")

    # fix
    p = subparsers.add_parser("fix", help="Auto-fix common SDRF errors")
    p.add_argument("sdrf_file")
    p.add_argument("-o", "--output")

    # benchmark
    p = subparsers.add_parser("benchmark", help="Benchmark SDRF quality across datasets")
    p.add_argument("sources", nargs="+")
    p.add_argument("--online", action="store_true")

    # crossval
    p = subparsers.add_parser("crossval", help="Cross-validate with multiple AI models")
    p.add_argument("project_info")
    p.add_argument("--cache-dir", default=None)

    # verify
    p = subparsers.add_parser("verify", help="Verify a single ontology accession")
    p.add_argument("accession", help="e.g. UNIMOD:1, MS:1001911")
    p.add_argument("--label", help="Expected label to verify against")

    args = parser.parse_args()

    commands = {
        "check": cmd_check,
        "score": cmd_score,
        "fix": cmd_fix,
        "benchmark": cmd_benchmark,
        "crossval": cmd_crossval,
        "verify": cmd_verify,
    }

    sys.exit(commands[args.command](args))


if __name__ == "__main__":
    main()
