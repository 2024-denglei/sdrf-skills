"""Unified CLI entry point for sdrf-skills tools.

Usage:
  python -m tools check <file.sdrf.tsv>          # hallucination check
  python -m tools score <file.sdrf.tsv>           # quality scoring
  python -m tools fix <file.sdrf.tsv> [-o out]    # auto-fix
  python -m tools benchmark <PXD1> <file2> ...    # benchmark suite
  python -m tools crossval <project_info>          # cross-validate
  python -m tools verify <ACCESSION> [--label L]   # verify single term
  python -m tools cellline lookup <name>           # curated cell line lookup
  python -m tools cellosaurus lookup <name>        # full Cellosaurus lookup
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
        return 0 if result.exists and result.label_match else 1
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


def cmd_cellline(args: argparse.Namespace) -> int:
    from tools.cellline_db import CellLineDatabase, annotate_sdrf_celllines
    from pathlib import Path

    if args.cellline_command == "lookup":
        db = CellLineDatabase()
        db.load(args.db)
        result = db.find(args.name)
        if result.entry:
            e = result.entry
            print(f"Cell line: {e.cell_line}")
            print(f"Match: {result.match_type} (confidence: {result.confidence:.2f})")
            print(f"Cellosaurus: {e.cellosaurus_name} ({e.cellosaurus_accession})")
            print(f"Organism: {e.organism}")
            print(f"Disease: {e.disease}")
            print(f"Tissue: {e.organism_part}")
            print(f"Cell type: {e.cell_type}")
            print(f"Age: {e.age}, Sex: {e.sex}")
            if e.synonyms:
                print(f"Synonyms: {'; '.join(e.synonyms[:10])}")
        else:
            print(f"'{args.name}' not found in database")
            return 1

    elif args.cellline_command == "annotate":
        enriched, report = annotate_sdrf_celllines(args.sdrf_file, db_path=args.db)
        print(report.summary())
        if args.output:
            Path(args.output).write_text(enriched)
            print(f"\nEnriched SDRF written to: {args.output}")

    elif args.cellline_command == "stats":
        db = CellLineDatabase()
        db.load(args.db)
        print(f"Cell Line Database: {db.size} entries, {len(db._index)} indexed names")

    return 0


def cmd_cellosaurus(args: argparse.Namespace) -> int:
    from tools.cellosaurus_db import CellosaurusDatabase, format_entry_display, format_entry_tsv

    if args.cellosaurus_command == "lookup":
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

    elif args.cellosaurus_command == "stats":
        db = CellosaurusDatabase()
        db.load(args.db)
        print(f"Cellosaurus Database: {db.size} entries, {len(db._name_index)} indexed names")

    elif args.cellosaurus_command == "search":
        from tools.cellosaurus_db import CellosaurusDatabase
        import difflib
        db = CellosaurusDatabase()
        db.load(args.db)
        results = []
        for accession, entry in db.entries.items():
            match_name = entry.cell_line or entry.cellosaurus_name or ""
            norm = db._normalize(match_name)
            if db._normalize(args.keyword) in norm or norm in db._normalize(args.keyword):
                ratio = difflib.SequenceMatcher(None, db._normalize(args.keyword), norm).ratio()
                results.append((ratio, entry))
            else:
                for syn in entry.synonyms + entry.synonyms_by_cellosaurus:
                    norm_syn = db._normalize(syn)
                    if db._normalize(args.keyword) in norm_syn or norm_syn in db._normalize(args.keyword):
                        ratio = difflib.SequenceMatcher(None, db._normalize(args.keyword), norm_syn).ratio()
                        results.append((ratio, entry))
                        break
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

    # cellline
    p = subparsers.add_parser("cellline", help="Cell line metadata lookup and annotation (curated subset)")
    cl_sub = p.add_subparsers(dest="cellline_command", required=True)
    cl_lookup = cl_sub.add_parser("lookup", help="Look up a cell line")
    cl_lookup.add_argument("name", help="Cell line name (e.g. HeLa, MCF-7)")
    cl_lookup.add_argument("--db", default=None)
    cl_annotate = cl_sub.add_parser("annotate", help="Annotate SDRF with cell line metadata")
    cl_annotate.add_argument("sdrf_file")
    cl_annotate.add_argument("-o", "--output")
    cl_annotate.add_argument("--db", default=None)
    cl_stats = cl_sub.add_parser("stats", help="Database statistics")
    cl_stats.add_argument("--db", default=None)

    # cellosaurus
    p = subparsers.add_parser("cellosaurus",
                              help="Full Cellosaurus database lookup (all ontology accessions)")
    cs_sub = p.add_subparsers(dest="cellosaurus_command", required=True)
    cs_lookup = cs_sub.add_parser("lookup", help="Look up a cell line by name or accession")
    cs_lookup.add_argument("name", help="Cell line name or accession (e.g. HeLa, CVCL_0030)")
    cs_lookup.add_argument("--db", default=None)
    cs_lookup.add_argument("--format", choices=["text", "tsv"], default="text",
                            help="Output format (default: text)")
    cs_stats = cs_sub.add_parser("stats", help="Show database statistics")
    cs_stats.add_argument("--db", default=None)
    cs_search = cs_sub.add_parser("search", help="Search cell lines by keyword")
    cs_search.add_argument("keyword", help="Keyword to search for")
    cs_search.add_argument("--db", default=None)
    cs_search.add_argument("--limit", type=int, default=10, help="Max results to show")

    args = parser.parse_args()

    # Set default db path for cellline commands
    if args.command == "cellline" and hasattr(args, "db") and args.db is None:
        from tools.cellline_db import DEFAULT_DB_PATH
        args.db = str(DEFAULT_DB_PATH)

    # Set default db path for cellosaurus commands
    if args.command == "cellosaurus" and hasattr(args, "db") and args.db is None:
        from tools.cellosaurus_db import DEFAULT_CELLOSAURUS_PATH
        args.db = str(DEFAULT_CELLOSAURUS_PATH)

    commands = {
        "check": cmd_check,
        "score": cmd_score,
        "fix": cmd_fix,
        "benchmark": cmd_benchmark,
        "crossval": cmd_crossval,
        "cellline": cmd_cellline,
        "cellosaurus": cmd_cellosaurus,
        "verify": cmd_verify,
    }

    sys.exit(commands[args.command](args))


if __name__ == "__main__":
    main()
