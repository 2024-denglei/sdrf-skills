# sdrf-skills Plugin - Brainstorm & Design Document

## Vision

An MCP (Model Context Protocol) server that gives Claude deep, structured access to the SDRF ecosystem — enabling it to **annotate**, **validate**, **improve**, and **brainstorm** proteomics metadata with expert-level precision. Instead of Claude having to guess at ontology terms or validation rules, it can call purpose-built tools that integrate with the real SDRF infrastructure.

---

## 1. Problem Space

When users ask Claude to help with SDRF files today, Claude:
- Has no access to the official SDRF templates or their validation rules
- Cannot validate ontology terms against OLS in real time
- Cannot look up real PRIDE project metadata for reference
- Cannot check if an SDRF file is valid without the user running sdrf-pipelines manually
- Cannot search for similar annotated datasets for guidance
- Cannot recommend correct terms from controlled vocabularies

**This plugin bridges that gap.**

---

## 2. Architecture Overview

```
┌──────────────────────────────────────────────────────────┐
│                    Claude (LLM)                          │
│                                                          │
│  User: "Help me annotate PXD012345"                      │
│  User: "Validate this SDRF file"                         │
│  User: "What tissue ontology term should I use for..."   │
└──────────────┬───────────────────────────────────────────┘
               │ MCP Protocol
               ▼
┌──────────────────────────────────────────────────────────┐
│              sdrf-skills MCP Server                        │
│                                                          │
│  ┌─────────────┐ ┌─────────────┐ ┌──────────────┐       │
│  │  Annotation  │ │ Validation  │ │   Discovery  │       │
│  │    Tools     │ │   Tools     │ │    Tools     │       │
│  └──────┬──────┘ └──────┬──────┘ └──────┬───────┘       │
│         │               │               │                │
│  ┌──────┴──────┐ ┌──────┴──────┐ ┌──────┴───────┐       │
│  │  Recommend  │ │  Analysis   │ │  Brainstorm  │       │
│  │    Tools    │ │   Tools     │ │    Tools     │       │
│  └──────┬──────┘ └──────┬──────┘ └──────┬───────┘       │
│         │               │               │                │
│         └───────────────┼───────────────┘                │
│                         │                                │
│              ┌──────────┴──────────┐                     │
│              │    Core Services    │                     │
│              │  - Template Engine  │                     │
│              │  - OLS Client       │                     │
│              │  - PRIDE Client     │                     │
│              │  - SDRF Parser      │                     │
│              │  - Term Dictionary  │                     │
│              └─────────────────────┘                     │
└──────────────────────────────────────────────────────────┘
               │               │              │
               ▼               ▼              ▼
        ┌──────────┐   ┌──────────┐   ┌──────────────┐
        │ EBI OLS4 │   │ PRIDE    │   │ sdrf-pipelines│
        │   API    │   │ REST API │   │  (embedded)   │
        └──────────┘   └──────────┘   └──────────────┘
```

---

## 2.1 Template-Aware Architecture (Cross-Cutting Concern)

**Every tool in the plugin should be template-aware.** Templates are not just for validation —
they define the vocabulary, constraints, and expectations for every SDRF operation.

### Template Layer System

The SDRF template system uses a layered inheritance model. When a user selects templates,
they combine layers to get the full set of rules:

```
LAYER 1: Technology (required, pick one)
  ├── ms-proteomics          (DDA/DIA mass spectrometry)
  └── affinity-proteomics    (Olink, SomaScan)

LAYER 2: Organism (optional, pick one — mutually exclusive)
  ├── human                  (disease staging, demographics, ancestry)
  ├── vertebrates            (mouse, rat, zebrafish — strain, breed)
  ├── invertebrates          (Drosophila, C. elegans)
  └── plants                 (Arabidopsis, crops)

LAYER 3: Experiment type (optional, pick any applicable)
  ├── cell-lines             (Cellosaurus codes, passage number)
  ├── dia-acquisition        (scan windows, isolation width)
  ├── single-cell            (cell isolation method, carrier proteome)
  ├── immunopeptidomics      (MHC typing, allele)
  ├── crosslinking           (crosslinker details)
  ├── phosphoproteomics      (enrichment method)
  ├── metaproteomics         (environmental samples — SPECIAL: extends base directly)
  ├── clinical-metadata      (clinical stage, treatment history)
  └── oncology-metadata      (tumor grade, TNM staging)

LAYER 4: Platform-specific (optional)
  ├── olink                  (panel name, LOD)
  └── somascan               (aptamer set version)
```

### Template Selection as First-Class Input

Most tools should accept a `templates` parameter (list of template names). When provided:

1. **Validation tools** apply the combined template rules
2. **Annotation tools** know which columns are required/optional
3. **Recommendation tools** suggest values appropriate for the template
4. **Education tools** explain requirements specific to the template combination

```
Example: User working on a human DIA phosphoproteomics experiment
  templates: ["ms-proteomics", "human", "dia-acquisition"]

  → sdrf_validate(..., templates=above)
    Validates against ALL columns from ms-proteomics + human + dia-acquisition

  → sdrf_recommend_terms("characteristics[disease]", templates=above)
    Returns human disease terms (EFO/MONDO) — wouldn't suggest plant diseases

  → sdrf_suggest_improvements(..., templates=above)
    Suggests DIA-specific columns (scan window, isolation width)
    Suggests human-specific columns (ancestry, developmental stage)
```

### Template Auto-Detection

When no templates are specified, the plugin can auto-detect from:
1. **SDRF metadata columns**: `comment[sdrf template]` contains `NT=ms-proteomics;VV=v1.1.0`
2. **Content heuristics**: Organism column → human/vertebrate/plant; DIA keywords → dia-acquisition
3. **PRIDE project metadata**: Organism and technology from PRIDE API

### Mutual Exclusivity Enforcement

The template system enforces mutual exclusivity:
- `human` excludes `vertebrates`, `invertebrates`, `plants`
- `ms-proteomics` excludes `affinity-proteomics`
- `metaproteomics` excludes all organism templates (uses own sample scheme)

If a user selects incompatible templates, the plugin warns immediately.

---

## 2.2 Publication-Enriched Annotation Pipeline (Cross-Cutting Concern)

**When a PXD accession is provided, the plugin should automatically find and leverage the
associated publication(s) to facilitate annotation.**

### The Problem

PRIDE project metadata alone is insufficient for SDRF annotation. It contains:
- Organism, instrument, modifications, file list (technical metadata)
- But NOT: tissue per sample, disease per sample, age, sex, cell type, experimental design

That information lives in the **publication** (abstract + methods + supplementary tables).

### The Pipeline: PXD → Publication → Structured Metadata

```
Step 1: PXD accession
        │
        ▼
Step 2: PRIDE API → project metadata
        │           (organism, instrument, PMID/DOI, file list)
        │
        ▼
Step 3: EuropePMC / PubMed → publication metadata
        │           (title, abstract, full text if OA)
        │
        ▼
Step 4: Full-text retrieval (if available via PMC)
        │           (methods section, sample tables, supplementary)
        │
        ▼
Step 5: Structured extraction by Claude
        │           (sample count, conditions, tissues, diseases, etc.)
        │
        ▼
Step 6: SDRF draft generation
                    (merge PRIDE technical + publication sample metadata)
```

### New Tools for This Pipeline

#### `sdrf_fetch_project_context`
**Purpose**: One-stop tool that retrieves ALL available context for a PXD accession.
**Input**: PXD accession
**Output**: Combined context object with PRIDE metadata + publication metadata + full text (if available)
**Backend**:
  1. PRIDE API `/projects/{PXD}` → organism, instrument, modifications, publications list
  2. Extract PMID/DOI from PRIDE response
  3. PubMed `get_article_metadata` → title, abstract, authors, MeSH terms
  4. PubMed `convert_article_ids` → check for PMC ID
  5. If PMC ID exists → `get_full_text_article` → methods section, sample tables
  6. EuropePMC `search_europepmc` → cross-reference, citation count, OA status

**Why**: This is the starting point for 90% of SDRF annotation tasks. Having all context
in one call lets Claude reason about what metadata to capture.

```json
{
  "pride": {
    "accession": "PXD012345",
    "title": "Quantitative proteomics of Alzheimer brain tissue",
    "organisms": ["Homo sapiens"],
    "instruments": ["Q Exactive HF"],
    "modifications": ["TMT6plex", "Oxidation", "Carbamidomethyl"],
    "sample_count": 24,
    "file_count": 288,
    "file_names": ["AD_brain_01_F01.raw", ...],
    "publications": [{"pmid": "34567890", "doi": "10.1038/..."}],
    "submission_date": "2023-06-15",
    "labels": ["TMT"]
  },
  "publication": {
    "pmid": "34567890",
    "title": "TMT-based quantitative proteomics reveals ...",
    "abstract": "We performed deep proteomic profiling of ...",
    "authors": ["Smith J", "Jones A", ...],
    "journal": "Nature Neuroscience",
    "year": 2023,
    "mesh_terms": ["Alzheimer Disease", "Brain", "Proteomics"],
    "has_full_text": true,
    "pmc_id": "PMC9876543"
  },
  "full_text_excerpt": {
    "methods": "Brain tissue samples were obtained from 12 AD patients and 12 age-matched controls. Temporal cortex and hippocampus were dissected... Samples were labeled with TMT6plex...",
    "sample_table": "Table 1: Patient demographics - Age (60-85), Sex (7M/5F per group), Braak stage (V-VI for AD, 0-II for control)..."
  },
  "suggested_templates": ["ms-proteomics", "human", "clinical-metadata"],
  "extracted_metadata": {
    "conditions": ["Alzheimer disease", "control"],
    "tissues": ["temporal cortex", "hippocampus"],
    "sample_count_per_condition": 12,
    "demographics_available": true,
    "fractionation": "12 fractions per sample"
  }
}
```

#### `sdrf_search_publication_by_accession`
**Purpose**: Find the publication associated with a dataset accession (PXD, MSV, PDC).
**Input**: Dataset accession
**Output**: Publication metadata (PMID, DOI, title, abstract, OA status)
**Backend**:
  1. Try PRIDE API first (most PXD have linked PMIDs)
  2. If not found → search EuropePMC for the accession string in full text
  3. If not found → search PubMed for accession in abstract/title
**Why**: Not all projects have PMIDs in PRIDE. Searching the literature by accession catches the rest.

```
Fallback chain:
  PRIDE API → publications[].pmid     (fastest, most reliable)
  EuropePMC → search("PXD012345")     (catches papers mentioning the accession)
  PubMed    → search("PXD012345")     (backup)
  bioRxiv   → search by title match   (catches preprints not yet in PubMed)
```

#### `sdrf_extract_metadata_from_paper`
**Purpose**: Extract SDRF-relevant metadata from a publication's text.
**Input**: PMID, DOI, or full text content
**Output**: Structured metadata extracted from the paper
**Backend**: Claude processes the text with SDRF-specific extraction prompts
**Extracts**:
  - Sample count and grouping
  - Organism, tissue, disease per group
  - Demographics (age, sex) if available
  - Experimental conditions / factor values
  - Technical details (instrument, labeling, fractionation)
  - Cell lines used (with Cellosaurus cross-reference)
  - Sample preparation (enzyme, modifications)

**Why**: This is the intelligence layer — turning unstructured paper text into structured SDRF columns.

#### `sdrf_enrich_from_mesh`
**Purpose**: Use MeSH terms from a PubMed entry to suggest SDRF ontology terms.
**Input**: PMID or list of MeSH terms
**Output**: Mapped SDRF columns and ontology terms
**Backend**: MeSH → SDRF column mapping dictionary

```
Example:
  MeSH terms: ["Alzheimer Disease", "Brain", "Proteomics", "Humans", "Aged"]
  Mapped to:
    characteristics[organism] → Homo sapiens (NCBITaxon:9606)
    characteristics[disease] → Alzheimer disease (MONDO:0004975)
    characteristics[organism part] → brain (UBERON:0000955)
    characteristics[developmental stage] → adult (EFO:0001272)
    technology type → proteomic profiling by mass spectrometry
```

### How This Changes the Annotation Workflow

**Before (current)**:
1. User gets PXD accession
2. User manually searches PRIDE website
3. User manually finds and reads the paper
4. User manually extracts sample info from methods section
5. User manually maps terms to ontologies
6. User fills SDRF by hand

**After (with plugin)**:
1. User gives PXD accession
2. `sdrf_fetch_project_context("PXD012345")` → everything in one call
3. Claude reads the context and drafts the SDRF automatically
4. `sdrf_annotate_column` maps extracted terms to ontologies
5. `sdrf_validate` confirms the result
6. User reviews and approves

**Time savings**: Hours → minutes for a typical 20-sample dataset.

---

## 3. Tool Categories & Detailed Design

### 3.1 VALIDATION TOOLS

#### `sdrf_validate`
**Purpose**: Validate an SDRF file against templates and ontology rules.
**Input**: SDRF content (TSV text or file path), template names (optional)
**Output**: Structured validation report (errors, warnings, suggestions)
**Backend**: Wraps sdrf-pipelines validation engine
**Why**: Core functionality — users can paste or upload SDRF content and get instant feedback without leaving the conversation.

```
Example workflow:
  User: "Validate this SDRF" → [pastes TSV]
  Claude → sdrf_validate(content, templates=["default", "human"])
  Returns: { errors: [...], warnings: [...], valid: false }
  Claude: "I found 3 errors: ..."
```

#### `sdrf_validate_column`
**Purpose**: Validate a single column's values against its expected ontology/format.
**Input**: Column name, list of values
**Output**: Per-value validation (valid/invalid, suggested corrections)
**Why**: Useful for incremental editing — validate as you go rather than the whole file.

#### `sdrf_check_ontology_term`
**Purpose**: Verify that a specific ontology term (accession + label) is valid.
**Input**: Ontology prefix (e.g., "EFO"), accession (e.g., "EFO:0000001"), label
**Output**: Valid/invalid, correct label, definition, synonyms, parent terms
**Backend**: OLS4 API (already available via MCP, but this wraps it for SDRF-specific context)
**Why**: The most common SDRF error is wrong ontology terms. This makes checking instant.

#### `sdrf_detect_template`
**Purpose**: Given an SDRF file or description, determine which templates should be applied.
**Input**: SDRF content or experiment description
**Output**: Recommended templates with confidence scores
**Why**: Users often don't know which template to use. This auto-detects from content.

---

### 3.2 ANNOTATION TOOLS

#### `sdrf_create_from_pride`
**Purpose**: Generate a draft SDRF file from a PRIDE project accession.
**Input**: PXD accession (e.g., "PXD012345")
**Output**: Pre-filled SDRF TSV with metadata from PRIDE
**Backend**: PRIDE REST API → extract organism, instrument, modifications, labels, files
**Why**: Most SDRF annotation starts from an existing PRIDE project. This bootstraps the process.

```
Example workflow:
  User: "Help me create an SDRF for PXD012345"
  Claude → sdrf_create_from_pride("PXD012345")
  Returns: Draft SDRF with known metadata filled in
  Claude → sdrf_validate(draft)
  Claude: "I created a draft with 45 samples.
           The instrument is Q Exactive HF.
           I still need: tissue, disease, cell type for each sample."
```

#### `sdrf_create_from_publication`
**Purpose**: Extract experimental metadata from a publication to seed an SDRF.
**Input**: PubMed ID or DOI
**Output**: Extracted metadata (organism, tissue, disease, sample count, etc.)
**Backend**: PubMed/EuropePMC API → parse abstract and methods
**Why**: When no PRIDE project exists, the publication is the primary metadata source.

#### `sdrf_annotate_column`
**Purpose**: Given a column name and free-text values, map them to proper ontology terms.
**Input**: Column name (e.g., "characteristics[disease]"), raw values (e.g., ["breast cancer", "normal", "lung adenocarcinoma"])
**Output**: Mapped ontology terms with accessions, confidence, alternatives
**Backend**: OLS4 search + SDRF term dictionary
**Why**: The hardest part of SDRF annotation is mapping free text to controlled vocabulary.

```
Example:
  Input:  column="characteristics[disease]", values=["breast cancer", "healthy"]
  Output: [
    { raw: "breast cancer", mapped: "breast carcinoma", accession: "EFO:0000305", confidence: 0.95 },
    { raw: "healthy", mapped: "normal", accession: "PATO:0000461", confidence: 0.90 }
  ]
```

#### `sdrf_suggest_factor_values`
**Purpose**: Recommend which columns should be factor values based on the experimental design.
**Input**: SDRF content or experiment description
**Output**: Suggested factor value columns with reasoning
**Why**: Factor values define the statistical comparison — getting them wrong breaks downstream analysis.

#### `sdrf_fill_technical_columns`
**Purpose**: Auto-fill technical columns (instrument, enzyme, modifications, labels) from project metadata.
**Input**: PXD accession or raw file analysis results
**Output**: Filled technical columns
**Backend**: PRIDE API + techSDRF parameter detection
**Why**: Technical columns are repetitive and error-prone. Most can be derived automatically.

---

### 3.3 DISCOVERY & REFERENCE TOOLS

#### `sdrf_search_examples`
**Purpose**: Find annotated SDRF examples similar to the user's experiment.
**Input**: Search criteria (organism, disease, instrument, experiment type)
**Output**: Matching datasets from the 250+ annotated collection with links
**Backend**: Index of multiomics-configs + proteomics-metadata-standard examples
**Why**: The best way to learn SDRF is by example. Finding relevant examples is key.

#### `sdrf_get_template_info`
**Purpose**: Get detailed information about an SDRF template.
**Input**: Template name (e.g., "human", "dia-acquisition")
**Output**: Required/optional columns, allowed values, inheritance chain, version
**Backend**: Parsed YAML template definitions
**Why**: Users need to understand what columns are required and what values are allowed.

#### `sdrf_list_templates`
**Purpose**: List all available SDRF templates with descriptions.
**Input**: None (or filter by organism/technology)
**Output**: Template catalog with metadata
**Why**: Discovery — users need to know what templates exist.

#### `sdrf_search_pride_projects`
**Purpose**: Search PRIDE for projects matching criteria.
**Input**: Keywords, organism, instrument, modification, etc.
**Output**: Matching PRIDE projects with metadata
**Backend**: PRIDE REST API (already available via PRIDE MCP)
**Why**: Finding reference projects is essential for annotation.

#### `sdrf_get_publication_metadata`
**Purpose**: Get structured metadata from a publication.
**Input**: PMID or DOI
**Output**: Title, abstract, methods, organism, sample info
**Backend**: PubMed/EuropePMC (already available via PubMed MCP)
**Why**: Publications contain the metadata needed for annotation.

---

### 3.4 RECOMMENDATION & IMPROVEMENT TOOLS

#### `sdrf_recommend_terms`
**Purpose**: Given a column and context, recommend appropriate ontology terms.
**Input**: Column name, experiment context (organism, technology)
**Output**: Ranked list of commonly used terms with accessions
**Backend**: Term frequency analysis from 250+ annotated datasets + OLS
**Why**: Instead of searching OLS from scratch, recommend terms that are actually used in SDRF.

```
Example:
  Input: column="characteristics[tissue]", context={organism: "Homo sapiens"}
  Output: [
    { term: "liver", accession: "UBERON:0002107", frequency: 45 },
    { term: "brain", accession: "UBERON:0000955", frequency: 38 },
    { term: "blood", accession: "UBERON:0000178", frequency: 67 },
    ...
  ]
```

#### `sdrf_suggest_improvements`
**Purpose**: Analyze an SDRF file and suggest improvements beyond validation errors.
**Input**: SDRF content
**Output**: Improvement suggestions (more specific terms, missing optional columns, etc.)
**Why**: Validation only catches errors. This tool suggests how to make metadata *better*.

Improvement categories:
- **Specificity**: "You used 'cancer' but 'breast invasive carcinoma' would be more precise"
- **Completeness**: "Consider adding 'characteristics[cell type]' — 80% of similar experiments include it"
- **Consistency**: "Row 5 uses 'Male' but rows 1-4 use 'male' — standardize case"
- **Best practices**: "This DIA experiment should use the dia-acquisition template"

#### `sdrf_fix_common_errors`
**Purpose**: Auto-fix known common errors in SDRF files.
**Input**: SDRF content + validation errors
**Output**: Corrected SDRF content with changelog
**Backend**: Pattern matching from the 204 datasets with known errors

Common auto-fixes:
- Wrong UNIMOD accessions (e.g., UNIMOD:21 → UNIMOD:1 for Acetyl)
- Missing ontology prefixes (e.g., "0000305" → "EFO:0000305")
- Python list artifacts (e.g., "['value']" → "value")
- DIA mislabeling (data-independent → data independent)
- Case normalization (Male → male)
- NT prefix issues (NT=XXX → accession format)

---

### 3.5 ANALYSIS & BRAINSTORM TOOLS

#### `sdrf_analyze_experimental_design`
**Purpose**: Analyze and summarize the experimental design from an SDRF file.
**Input**: SDRF content
**Output**: Design summary (sample groups, replicates, conditions, comparisons)
**Why**: Helps users understand the statistical structure of their experiment.

```
Example output:
  Design: 2-condition comparison
  Factor: disease (breast carcinoma vs normal)
  Samples: 10 per group (20 total)
  Replicates: 3 biological × 2 technical
  Fractions: 12 per sample
  Label: TMT10plex
  Total files: 480
```

#### `sdrf_brainstorm_metadata`
**Purpose**: Help users think through what metadata to capture for their experiment type.
**Input**: Experiment description (free text)
**Output**: Recommended columns, templates, ontology sources, and design considerations
**Why**: Before creating an SDRF, users need to plan what metadata to capture.

#### `sdrf_compare_datasets`
**Purpose**: Compare two SDRF files or a file against reference datasets.
**Input**: Two SDRF contents or one SDRF + reference criteria
**Output**: Differences, missing columns, quality comparison
**Why**: Useful for quality assessment and learning from well-annotated datasets.

#### `sdrf_literature_context`
**Purpose**: Search the literature for experimental context relevant to an SDRF.
**Input**: Organism, disease, tissue, technology keywords
**Output**: Relevant papers, common experimental designs, standard practices
**Backend**: PubMed + bioRxiv + Consensus MCP tools
**Why**: Understanding the scientific context helps make better annotation decisions.

---

## 4. MCP Resources (Read-Only Data)

In addition to tools, the MCP server should expose resources that Claude can read:

| Resource URI | Description |
|---|---|
| `sdrf://templates` | List of all available templates |
| `sdrf://templates/{name}` | Full template definition (YAML) |
| `sdrf://terms/{column}` | Valid terms for a column |
| `sdrf://examples` | Index of annotated example datasets |
| `sdrf://examples/{pxd}` | Example SDRF file for a dataset |
| `sdrf://spec/columns` | Column naming conventions and format |
| `sdrf://spec/ontologies` | Supported ontologies and their usage |
| `sdrf://changelog` | Recent changes to templates/spec |

---

## 5. Integration with Existing MCP Servers

The plugin should leverage (not duplicate) existing MCP servers:

| External MCP | How sdrf-skills Uses It | Key Functions Used |
|---|---|---|
| **OLS** | Term validation, ontology search, ancestor/descendant lookups for EFO, CL, UBERON, MS, UNIMOD, NCBI Taxonomy | `search`, `fetch`, `getAncestors`, `getDescendants`, `searchClasses` |
| **PRIDE MCP** | Project metadata, file listings, publication links, dataset search | `fetch_projects`, `get_project_details`, `get_project_files`, `search_extensive` |
| **PubMed** | Publication metadata, full text retrieval, ID conversion | `search_articles`, `get_article_metadata`, `get_full_text_article`, `convert_article_ids` |
| **bioRxiv** | Recent preprints for cutting-edge experimental designs | `search_preprints`, `get_preprint` |
| **Consensus** | Peer-reviewed evidence for metadata decisions | `search` |
| **Open Targets** | Disease-target associations for disease term selection | `search_entities`, `query_open_targets_graphql` |
| **EuropePMC** (via PRIDE) | Full-text search, citation info, OA articles | `search_europepmc`, `get_europepmc_article` |

**Key principle**: sdrf-skills adds SDRF-specific intelligence *on top of* these general tools.

For example:
- OLS can search for any ontology term, but sdrf-skills knows *which* ontology to search for each SDRF column
- PRIDE can return project metadata, but sdrf-skills knows how to *transform* it into SDRF format
- PubMed can find papers, but sdrf-skills knows how to *extract* SDRF-relevant metadata from them

### Publication Retrieval Chain (PXD → Paper → Metadata)

When `sdrf_fetch_project_context` is called with a PXD accession, the plugin orchestrates
multiple MCP calls to build complete context:

```
1. PRIDE MCP: get_project_details(PXD012345)
   → organism, instrument, modifications, publications[{pmid, doi}], files

2. PubMed MCP: get_article_metadata([pmid])
   → title, abstract, authors, journal, MeSH terms

3. PubMed MCP: convert_article_ids([pmid])
   → check for PMC ID (full text availability)

4. PubMed MCP: get_full_text_article([pmc_id])  — if PMC ID exists
   → methods section, sample tables, supplementary info

5. FALLBACK — if no PMID in PRIDE:
   EuropePMC: search_europepmc("PXD012345")
   → find papers mentioning the accession in full text

6. FALLBACK — if only preprint:
   bioRxiv: search_preprints(title keywords)
   → find preprint version
```

This chain is critical because:
- **PRIDE has the technical metadata** (what instrument, what labels, what files)
- **The paper has the sample metadata** (which tissue, which disease, which patients)
- **Both are needed** to create a complete SDRF

---

## 6. Technology Stack

```
Language:      Python 3.11+ (matches sdrf-pipelines ecosystem)
MCP Framework: mcp (official Python SDK for MCP servers)
Validation:    sdrf-pipelines (imported as library, not CLI)
HTTP Client:   httpx (async, for OLS/PRIDE API calls)
Data:          pandas (SDRF parsing), pydantic (schemas)
Packaging:     uv (fast, modern Python packaging)
Testing:       pytest + pytest-asyncio
```

### Project Structure

```
sdrf-skills/
├── src/
│   └── sdrf-skills/
│       ├── __init__.py
│       ├── server.py              # MCP server entry point
│       ├── tools/
│       │   ├── __init__.py
│       │   ├── validation.py      # sdrf_validate, sdrf_check_ontology_term, ...
│       │   ├── annotation.py      # sdrf_create_from_pride, sdrf_annotate_column, ...
│       │   ├── discovery.py       # sdrf_search_examples, sdrf_list_templates, ...
│       │   ├── recommendation.py  # sdrf_recommend_terms, sdrf_suggest_improvements, ...
│       │   ├── analysis.py        # sdrf_analyze_design, sdrf_brainstorm, ...
│       │   ├── pipeline.py        # sdrf_convert, sdrf_recommend_pipeline, ...
│       │   ├── publication.py     # sdrf_fetch_project_context, sdrf_extract_metadata_from_paper, ...
│       │   └── templates.py       # sdrf_select_templates, sdrf_get_template_info, ...
│       ├── clients/
│       │   ├── __init__.py
│       │   ├── ols.py             # OLS4 API client (async)
│       │   ├── pride.py           # PRIDE REST API client (async) — project + file metadata
│       │   ├── pubmed.py          # PubMed/EuropePMC client (async) — publication retrieval
│       │   └── sdrf_pipelines.py  # Wrapper around sdrf-pipelines library
│       ├── core/
│       │   ├── __init__.py
│       │   ├── template_engine.py # Template loading, inheritance, combination, auto-detection
│       │   ├── publication_chain.py # PXD → PRIDE → PubMed → PMC full text pipeline
│       │   └── context.py         # AnnotationContext: holds templates + project + publication state
│       ├── data/
│       │   ├── term_dictionary.json    # Pre-built term frequency index
│       │   ├── common_errors.json      # Known error patterns + fixes
│       │   ├── example_index.json      # Index of annotated datasets
│       │   ├── column_ontology_map.json # Column name → allowed ontologies mapping
│       │   └── mesh_sdrf_map.json      # MeSH term → SDRF column mapping
│       ├── resources/
│       │   ├── __init__.py
│       │   └── providers.py       # MCP resource providers
│       └── utils/
│           ├── __init__.py
│           ├── parsing.py         # SDRF TSV parsing utilities
│           └── ontology.py        # Ontology mapping helpers
├── tests/
│   ├── test_validation.py
│   ├── test_annotation.py
│   ├── test_discovery.py
│   ├── test_recommendation.py
│   ├── test_publication_chain.py
│   ├── test_template_engine.py
│   └── fixtures/
│       ├── sample_sdrf.tsv
│       ├── pride_response.json    # Mock PRIDE API response
│       └── pubmed_response.json   # Mock PubMed response
├── pyproject.toml
├── README.md
├── BRAINSTORM.md                  # This file
└── CLAUDE.md                      # Instructions for Claude
```

---

## 7. User Workflow Examples

### Workflow 1: Annotate a new PRIDE dataset (template-aware + publication-enriched)

```
User: "I need to create an SDRF for PXD045678"

Claude:
  1. sdrf_fetch_project_context("PXD045678")
     → PRIDE metadata: organism=human, instrument=Q Exactive HF, TMT6plex, 24 samples
     → Publication: PMID=34567890, "TMT proteomics of Alzheimer brain tissue"
     → Full text: methods section with sample table (12 AD, 12 control, temporal cortex)
     → MeSH terms: Alzheimer Disease, Brain, Humans, Aged

  2. sdrf_detect_template(context)
     → Recommended: ["ms-proteomics", "human", "clinical-metadata"]
     → Reasoning: human samples, TMT labeling, disease study with clinical staging

  3. sdrf_create_from_pride("PXD045678", templates=["ms-proteomics", "human", "clinical-metadata"])
     → Draft SDRF with:
        - Technical columns filled from PRIDE (instrument, label, modifications, files)
        - Sample columns pre-filled from publication (disease, tissue, age, sex)
        - Template-required columns included (even if empty)

  4. sdrf_annotate_column("characteristics[disease]",
       values=["Alzheimer disease", "control"],
       templates=["human"])
     → Mapped: Alzheimer disease → MONDO:0004975, control → PATO:0000461

  5. sdrf_validate(completed_sdrf, templates=["ms-proteomics", "human", "clinical-metadata"])
     → Final validation against all 3 template layers

  6. sdrf_suggest_improvements(completed_sdrf, templates=above)
     → "Consider adding Braak stage to characteristics[disease staging]
        (required by clinical-metadata template, available in paper Table 1)"
```

### Workflow 2: Fix validation errors (template-aware)

```
User: "This SDRF has errors, can you fix it?" [pastes content]

Claude:
  1. sdrf_detect_template(content)
     → Detected from comment[sdrf template]: ms-proteomics v1.1.0
     → Auto-detected from content: human (organism=Homo sapiens)

  2. sdrf_validate(content, templates=["ms-proteomics", "human"])
     → 5 errors, 3 warnings

  3. sdrf_fix_common_errors(content, errors)
     → Fixed: UNIMOD:21→UNIMOD:1 (Acetyl), case normalization, missing prefix

  4. sdrf_check_ontology_term("breast cancer", ontology="EFO")
     → Suggestion: use "breast carcinoma" (EFO:0000305) — more specific

  5. sdrf_validate(fixed_content, templates=["ms-proteomics", "human"])
     → 0 errors, 1 warning (optional column missing)

  6. Return corrected SDRF
```

### Workflow 3: Brainstorm experimental design (template-guided)

```
User: "I'm planning a phosphoproteomics study of liver cancer,
       what metadata should I capture?"

Claude:
  1. sdrf_select_templates(description="phosphoproteomics, human liver cancer")
     → Recommended: ["ms-proteomics", "human", "clinical-metadata", "oncology-metadata"]
     → Reasoning: human cancer study → need oncology staging columns

  2. sdrf_get_template_info(["ms-proteomics", "human", "clinical-metadata", "oncology-metadata"])
     → Combined required columns: 28 columns
     → Combined optional columns: 15 columns
     → Special requirements: Phospho modification must be declared, tumor staging columns

  3. sdrf_search_examples(organism="human", disease="liver cancer", modification="phospho")
     → 3 similar datasets found with links

  4. sdrf_brainstorm_metadata(description, templates=above)
     → Recommended columns with reasoning:
       REQUIRED: organism, disease, organism part, age, sex, instrument, label, ...
       RECOMMENDED: tumor grade, TNM stage, treatment history, cell type, ...
       PHOSPHO-SPECIFIC: enrichment method (e.g., IMAC, TiO2), ...

  5. sdrf_literature_context("phosphoproteomics liver cancer")
     → Recent papers showing common experimental designs (PubMed + bioRxiv)
     → Typical sample sizes: 10-30 patients per group
     → Typical labels: TMT (70%), SILAC (15%), label-free (15%)
  4. sdrf_literature_context(keywords)          → Common designs in literature
  5. sdrf_recommend_terms("disease", liver_cancer) → Specific terms to use
```

### Workflow 4: Improve existing SDRF

```
User: "How can I improve this SDRF?" [provides file]

Claude:
  1. sdrf_validate(content)                    → Current errors/warnings
  2. sdrf_suggest_improvements(content)        → Quality suggestions
  3. sdrf_compare_datasets(content, reference) → Gap analysis vs best examples
  4. sdrf_recommend_terms(column, context)     → Better term suggestions
  5. Return prioritized improvement plan
```

---

## 8. Term Dictionary: Pre-built Knowledge Base

A key differentiator is a **pre-built term dictionary** extracted from the 250+ annotated datasets:

```json
{
  "characteristics[organism]": {
    "Homo sapiens": { "accession": "NCBITaxon:9606", "frequency": 198 },
    "Mus musculus": { "accession": "NCBITaxon:10090", "frequency": 87 },
    "Rattus norvegicus": { "accession": "NCBITaxon:10116", "frequency": 23 },
    ...
  },
  "characteristics[disease]": {
    "breast carcinoma": { "accession": "EFO:0000305", "frequency": 15 },
    "normal": { "accession": "PATO:0000461", "frequency": 145 },
    "lung adenocarcinoma": { "accession": "EFO:0000571", "frequency": 8 },
    ...
  },
  "characteristics[cell type]": {
    "epithelial cell": { "accession": "CL:0000066", "frequency": 12 },
    "T cell": { "accession": "CL:0000084", "frequency": 9 },
    ...
  }
}
```

This dictionary serves dual purposes:
1. **Fast recommendations** without OLS API calls
2. **Validation** that terms are actually used in the SDRF ecosystem (not just valid in OLS)

Source: Build by parsing all SDRF files in multiomics-configs + proteomics-metadata-standard.

---

## 9. Common Error Patterns Database

Pre-built database of the most frequent SDRF errors from analyzing 204 datasets with errors:

| Error Pattern | Frequency | Auto-Fix |
|---|---|---|
| Wrong UNIMOD accession | 45% | Map to correct accession |
| Missing ontology prefix | 30% | Add correct prefix |
| Case mismatch | 25% | Normalize to lowercase |
| Python list artifacts `['val']` | 15% | Strip brackets/quotes |
| DIA/DDA mislabeling | 10% | Correct terminology |
| Not an children term | 20% | Suggest valid parent term |
| Missing required columns | 35% | Add with default values |
| Wrong column name format | 20% | Fix to `characteristics[x]` |

---

## 10. Implementation Phases (Revised)

### Phase 1: Foundation (MVP)
- MCP server skeleton with tool registration
- **Template engine**: `sdrf_list_templates`, `sdrf_get_template_info`, `sdrf_select_templates`, `sdrf_detect_template`
- **Validation**: `sdrf_validate` (template-aware, wrapping sdrf-pipelines)
- **Ontology**: `sdrf_check_ontology_term`, `sdrf_ontology_column_mapping`
- **Education**: `sdrf_explain_column`, `sdrf_explain_error`
- Basic SDRF parsing utilities
- CLAUDE.md with usage instructions

### Phase 2: Annotation + Publication Pipeline
- **Publication chain**: `sdrf_fetch_project_context`, `sdrf_search_publication_by_accession`, `sdrf_extract_metadata_from_paper`, `sdrf_enrich_from_mesh`
- **Annotation**: `sdrf_create_from_pride` (template-aware + publication-enriched), `sdrf_annotate_column`, `sdrf_fill_technical_columns`
- **Recommendation**: `sdrf_recommend_terms` (term dictionary)
- Term dictionary build script
- PRIDE API + PubMed/EuropePMC client integration

### Phase 3: Intelligence
- `sdrf_suggest_improvements` (template-aware)
- `sdrf_fix_common_errors`
- `sdrf_brainstorm_metadata` (template-guided)
- `sdrf_analyze_experimental_design`
- `sdrf_detect_batch_effects`, `sdrf_detect_confounders`, `sdrf_assess_replication`
- Common error patterns database

### Phase 4: Discovery, Community & Integration
- `sdrf_search_examples`, `sdrf_find_similar_experiments`
- `sdrf_create_from_publication`, `sdrf_literature_context`
- `sdrf_compare_datasets`, `sdrf_community_stats`
- `sdrf_convert`, `sdrf_recommend_pipeline`
- MCP resource providers, CI/CD tools

---

## 11. Key Design Decisions

1. **Python over TypeScript**: The SDRF ecosystem is Python-based. Using Python allows direct import of sdrf-pipelines as a library rather than wrapping it as a subprocess.

2. **MCP over REST API**: MCP is purpose-built for LLM tool access. It handles tool discovery, schema validation, and streaming natively.

3. **Embedded validation over API calls**: Import sdrf-pipelines directly rather than calling the sdrf-validator-api. Faster, no network dependency, full access to internals.

4. **Pre-built dictionaries over live search**: For common terms, a pre-built dictionary is faster and more relevant than OLS search. OLS is the fallback for uncommon terms.

5. **Structured output over free text**: All tools return structured JSON, letting Claude format the response appropriately for the user's context.

6. **Composable tools over monolithic endpoints**: Many small, focused tools that Claude can combine creatively, rather than few large endpoints that try to do everything.

---

## 12. EXPANDED TOOL CATALOG — Additional Functions

After deep analysis of the full SDRF ecosystem (sdrf-pipelines' 20 validators & 5 converters,
techsdrf's raw-file auto-detection, sdrfedit's AI panel, and 681 annotated datasets), here are
all the additional function categories the plugin should support:

---

### 12.1 CONVERSION & PIPELINE INTEGRATION TOOLS

These wrap sdrf-pipelines converters but add **intelligence** — Claude doesn't just convert,
it helps users **choose** and **configure** the right pipeline.

#### `sdrf_convert`
**Purpose**: Convert an SDRF to a specific pipeline format.
**Input**: SDRF content, target format (openms | maxquant | diann | msstats | normalyzerde)
**Output**: Converted configuration files (TSV, XML, or CFG depending on format)
**Backend**: Wraps the 5 existing sdrf-pipelines converters (OpenMS, MaxQuant, DIA-NN, MSstats, NormalyzerDE)
**Why**: Users can go from SDRF to analysis-ready config in one step.

#### `sdrf_recommend_pipeline`
**Purpose**: Recommend the best analysis pipeline based on the experimental design in the SDRF.
**Input**: SDRF content or experiment description
**Output**: Ranked pipeline recommendations with rationale
**Logic**:
  - DIA data → recommend DIA-NN or Spectronaut
  - TMT/iTRAQ → recommend MaxQuant or OpenMS with MSstats
  - Label-free DDA → recommend MaxQuant or OpenMS
  - Large cohort (>100 samples) → recommend DIA-NN for speed
  - Phosphoproteomics → recommend MaxQuant with PTM scoring
  - Single-cell → recommend specialized workflows
**Why**: New users don't know which pipeline fits their experiment. Claude can reason about it.

#### `sdrf_check_pipeline_compatibility`
**Purpose**: Verify that an SDRF file is compatible with a specific analysis pipeline.
**Input**: SDRF content, target pipeline name
**Output**: Compatibility report — missing columns, unsupported values, required changes
**Why**: Each pipeline needs different columns/values. Catch incompatibilities before analysis.

```
Example:
  Input: SDRF with TMT data → target: "diann"
  Output: {
    compatible: false,
    issues: ["DIA-NN does not support TMT. Consider MaxQuant or OpenMS."],
    suggestions: ["If using PlexDIA, DIA-NN supports mTRAQ/SILAC-DIA labels."]
  }
```

#### `sdrf_generate_quantms_config`
**Purpose**: Generate a full quantms (Nextflow) pipeline configuration from an SDRF.
**Input**: SDRF content
**Output**: nextflow.config parameters, sample sheet, run command
**Backend**: Understands quantms pipeline parameters and maps from SDRF columns
**Why**: quantms is the primary cloud pipeline for SDRF-driven proteomics. Direct integration removes manual config.

---

### 12.2 RAW FILE INTELLIGENCE TOOLS (via techsdrf)

techsdrf can auto-detect parameters from raw MS files. These tools bridge that into the SDRF workflow.

#### `sdrf_detect_parameters`
**Purpose**: Analyze raw MS files (from PRIDE) and detect instrument/method parameters.
**Input**: PXD accession or list of raw file names
**Output**: Detected parameters with confidence scores (instrument, fragmentation, tolerances, labels, DDA/DIA, charge range, collision energy, etc.)
**Backend**: techsdrf analyzer (Thermo RAW, Bruker .d, Waters, AB SCIEX support)
**Why**: Technical SDRF columns can be auto-filled from actual instrument data.

#### `sdrf_compare_declared_vs_detected`
**Purpose**: Compare parameters declared in SDRF vs detected from raw files.
**Input**: SDRF content + PXD accession (or detected parameters)
**Output**: Match/mismatch report per parameter with confidence
**Status levels**: MATCH, MISMATCH, MISSING_SDRF, MISSING_DETECTED, IMPROVED
**Why**: Catches wrong instrument models, incorrect mass tolerances, mislabeled DDA/DIA, etc.

```
Example output:
  instrument:  MATCH   (Q Exactive HF — confirmed from raw header)
  tolerance:   MISMATCH (SDRF: 10 ppm, detected: 5.2 ppm — SDRF too loose)
  label:       MATCH   (label free — no reporter ions detected)
  dissociation: MISSING_SDRF (detected: HCD, 28% NCE — add to SDRF)
```

#### `sdrf_detect_ptms`
**Purpose**: Detect post-translational modifications from raw spectra without database search.
**Input**: PXD accession or raw file list
**Output**: Detected PTMs with evidence (reporter ions, diagnostic ions, mass shifts)
**Backend**: techsdrf's 3-tier PTM detector
**Why**: Validates that declared modifications match actual data. Catches common errors like declaring TMT but data is label-free.

---

### 12.3 ONTOLOGY DEEP REASONING TOOLS

Beyond simple OLS search — SDRF-aware ontology intelligence.

#### `sdrf_ontology_navigate`
**Purpose**: Navigate the ontology hierarchy for a term — parents, children, siblings.
**Input**: Ontology term (accession or label), direction (up/down/siblings), depth
**Output**: Hierarchical tree of related terms with accessions
**Backend**: OLS4 ancestor/descendant API
**Why**: Users need to find the RIGHT level of specificity. "breast" is too vague, "left breast upper inner quadrant" is too specific.

#### `sdrf_cross_ontology_map`
**Purpose**: Map a term across equivalent ontologies.
**Input**: Term from one ontology (e.g., EFO:0000305)
**Output**: Equivalent terms in other ontologies (MONDO, DOID, NCIT, OMIM)
**Why**: SDRF supports multiple disease ontologies (EFO, MONDO, DOID). Users often have a term from one and need the other.

```
Example:
  Input: "breast carcinoma" (EFO:0000305)
  Output: {
    EFO:  "EFO:0000305 — breast carcinoma",
    MONDO: "MONDO:0007254 — breast cancer",
    DOID:  "DOID:1612 — breast cancer",
    NCIT:  "NCIT:C4872 — breast carcinoma"
  }
```

#### `sdrf_validate_term_specificity`
**Purpose**: Check if a term is specific enough for SDRF context, or too generic.
**Input**: Column name, ontology term, experiment context
**Output**: Specificity assessment (too_generic | appropriate | too_specific), alternative suggestions
**Logic**: Uses descendant count and position in hierarchy relative to what similar datasets use
**Why**: "cancer" (EFO:0000311) has 1000+ children — always too generic for characteristics[disease].

#### `sdrf_ontology_column_mapping`
**Purpose**: For a given SDRF column, return which ontologies are valid and their roots.
**Input**: Column name (e.g., "characteristics[cell type]")
**Output**: Allowed ontologies, root terms, search URLs, example values
**Backend**: Hard-coded from SDRF spec + template YAML definitions
**Why**: Users don't know to search CL for cell types, UBERON for tissues, EFO for diseases, etc.

```
Example:
  Input: "characteristics[cell type]"
  Output: {
    ontologies: [
      { id: "CL", name: "Cell Ontology", root: "CL:0000000", preferred: true },
      { id: "BTO", name: "BRENDA Tissue Ontology", root: "BTO:0000000" }
    ],
    common_values: ["epithelial cell", "T cell", "fibroblast", ...],
    reserved_words: ["not applicable", "not available"]
  }
```

---

### 12.4 EXPERIMENTAL DESIGN INTELLIGENCE TOOLS

Statistical reasoning about the experimental design encoded in the SDRF.

#### `sdrf_detect_batch_effects`
**Purpose**: Identify potential batch effects from SDRF metadata.
**Input**: SDRF content
**Output**: Detected batch confounds with severity
**Logic**: Cross-tabulate factor values against technical variables (instrument, date, fraction, label channel)
**Why**: If all disease samples ran on Monday and all controls on Friday → batch effect.

```
Example:
  WARNING: Factor "disease" is perfectly confounded with "comment[instrument]"
    - All "carcinoma" samples on Q Exactive HF
    - All "normal" samples on Orbitrap Fusion
    → Biological signal cannot be separated from instrument effect
```

#### `sdrf_detect_confounders`
**Purpose**: Identify confounding variables in the experimental design.
**Input**: SDRF content
**Output**: Confounding variable pairs with severity
**Logic**: Check independence of factor values from other characteristics (age, sex, tissue)
**Why**: If all female samples are disease and all male are control → sex is a confounder.

#### `sdrf_assess_replication`
**Purpose**: Assess whether the experiment has adequate replication.
**Input**: SDRF content
**Output**: Replication summary per condition, recommendations
**Logic**: Count biological replicates, technical replicates, and fractions per condition
**Why**: Users often don't realize they have n=1 biological replicates per condition.

```
Example:
  Condition "treatment": 3 biological replicates × 2 technical × 12 fractions = 72 files
  Condition "control":   1 biological replicate × 2 technical × 12 fractions = 24 files
  WARNING: "control" has only 1 biological replicate — insufficient for statistical testing.
```

#### `sdrf_suggest_comparisons`
**Purpose**: Suggest statistical comparisons based on the experimental design.
**Input**: SDRF content
**Output**: Possible pairwise/multi-group comparisons with MSstats contrast matrix
**Why**: Helps users define the right comparisons for downstream analysis (MSstats, limma, etc.).

---

### 12.5 DATA CLEANING & NORMALIZATION TOOLS

Targeted at the 204 datasets with known errors and the common quality issues.

#### `sdrf_normalize_values`
**Purpose**: Normalize free-text values to standard SDRF format.
**Input**: Column name, list of raw values
**Output**: Normalized values with changes highlighted
**Normalizations**:
  - Case: "Male" → "male", "Breast Cancer" → "breast cancer"
  - Whitespace: trim leading/trailing, collapse double spaces
  - Encoding: fix UTF-8 artifacts, curly quotes → straight quotes
  - Format: "58 years" → "58Y", "10 ppm" → "10 ppm"
  - Reserved words: "N/A" → "not available", "NA" → "not applicable"
  - Python artifacts: "['value']" → "value", "nan" → "not available"

#### `sdrf_standardize_modifications`
**Purpose**: Standardize modification parameter strings to correct SDRF format.
**Input**: Modification strings (free text or malformed NT/AC format)
**Output**: Corrected modification strings with proper UNIMOD accessions
**Backend**: UNIMOD dictionary + common misspelling corrections
**Why**: Modification formatting is the #1 source of SDRF errors (45% of all errors).

```
Example:
  Input:  "Carbamidomethyl (C)"
  Output: "NT=Carbamidomethyl;AC=UNIMOD:4;TA=C;MT=Fixed"

  Input:  "NT=Acetyl;AC=UNIMOD:21;TA=Protein N-term;MT=Variable"
  Output: "NT=Acetyl;AC=UNIMOD:1;TA=Protein N-term;MT=Variable"  ← Fixed: UNIMOD:21→UNIMOD:1
```

#### `sdrf_deduplicate_rows`
**Purpose**: Detect and remove/flag duplicate rows in an SDRF file.
**Input**: SDRF content
**Output**: Duplicate groups, suggested resolution
**Why**: Copy-paste errors create duplicate sample-file mappings that break analysis.

#### `sdrf_validate_file_references`
**Purpose**: Check that data file references in SDRF actually exist in PRIDE/repository.
**Input**: SDRF content + PXD accession
**Output**: File-by-file validation (exists/missing/extra files not in SDRF)
**Backend**: PRIDE file listing API
**Why**: Missing or misspelled file names prevent analysis pipeline execution.

```
Example:
  Files in SDRF but NOT in PRIDE:
    - sample_01.raw  (typo? PRIDE has "Sample_01.raw")
  Files in PRIDE but NOT in SDRF:
    - QC_run_01.raw  (quality control run — expected to be excluded)
    - blank_01.raw   (blank run — expected to be excluded)
```

---

### 12.6 CROSS-DATASET INTELLIGENCE TOOLS

Leverage the 681 datasets (445K samples) as a knowledge base.

#### `sdrf_find_similar_experiments`
**Purpose**: Find the most similar annotated experiments to a given SDRF or description.
**Input**: SDRF content or experiment description (organism, tissue, disease, technology)
**Output**: Top-N similar datasets with similarity scores and links
**Backend**: Pre-built index over 681 datasets with feature vectors
**Why**: Learning by example is the fastest way to annotate well.

#### `sdrf_term_usage_stats`
**Purpose**: Get usage statistics for a term across the annotated dataset collection.
**Input**: Column name, term value
**Output**: Frequency, co-occurring terms, typical experiment contexts
**Why**: Know if a term is commonly used (trusted) or rare (needs review).

```
Example:
  Input: column="characteristics[disease]", term="colorectal cancer"
  Output: {
    frequency: 12 datasets,
    common_co_terms: {
      organism: "Homo sapiens (100%)",
      tissue: ["colon (67%)", "rectum (17%)", "blood (16%)"],
      cell_type: ["epithelial cell (42%)", "not available (58%)"]
    },
    typical_labels: ["TMT (50%)", "label free (33%)", "SILAC (17%)"],
    example_datasets: ["PXD012345", "PXD023456", ...]
  }
```

#### `sdrf_column_completeness_report`
**Purpose**: Report which optional columns are used by similar experiments.
**Input**: SDRF content (to determine experiment type) or experiment description
**Output**: Column-by-column completeness percentage in similar datasets
**Why**: Tells users "80% of human tissue studies include cell type — you should too."

#### `sdrf_trending_terms`
**Purpose**: Show which ontology terms are trending (increasing usage) in recent annotations.
**Input**: Column name, time range (optional)
**Output**: Terms ranked by growth rate
**Why**: Community conventions evolve — e.g., "not available" replacing "N/A", new cell type terms.

---

### 12.7 COMPLIANCE & REPORTING TOOLS

#### `sdrf_miape_compliance`
**Purpose**: Check SDRF compliance with MIAPE (Minimum Information About a Proteomics Experiment).
**Input**: SDRF content
**Output**: MIAPE checklist with pass/fail per requirement
**Why**: Journals and funding agencies increasingly require MIAPE compliance.

#### `sdrf_generate_submission_report`
**Purpose**: Generate a human-readable report summarizing the SDRF for PRIDE submission.
**Input**: SDRF content
**Output**: Formatted report (Markdown or PDF-ready) with experiment summary, sample table, technical overview
**Why**: PRIDE reviewers need a quick overview. This auto-generates it from the SDRF.

```
Example output:
  # SDRF Submission Report
  ## Experiment Summary
  - Organism: Homo sapiens
  - Disease: breast carcinoma vs normal
  - Tissue: breast, adjacent normal
  - Technology: TMT10plex, Q Exactive HF
  - Samples: 20 (10 disease + 10 control)
  - Files: 240 (12 fractions × 20 samples)
  ## Quality Assessment
  - Template compliance: ✓ human, ms-proteomics
  - Ontology validation: ✓ all terms valid
  - Completeness: 95% (missing: cell type)
```

#### `sdrf_generate_methods_section`
**Purpose**: Draft a methods section paragraph from SDRF metadata.
**Input**: SDRF content
**Output**: Publication-ready methods text
**Why**: The SDRF contains exactly the metadata that belongs in a methods section. Auto-generating saves time and ensures consistency.

```
Example:
  "Samples were analyzed on a Q Exactive HF mass spectrometer (Thermo Fisher).
   Proteins were digested with Trypsin/P and labeled with TMT10plex reagents.
   Peptides were separated by reversed-phase chromatography into 12 fractions.
   Data were acquired in data-dependent acquisition (DDA) mode with HCD
   fragmentation at 28% normalized collision energy..."
```

#### `sdrf_quality_score`
**Purpose**: Calculate an overall quality score for an SDRF file (0-100).
**Input**: SDRF content
**Output**: Score with breakdown by category (completeness, specificity, consistency, standards compliance)
**Why**: Gives users a single number to track improvement and compare quality.

```
Example:
  Overall: 72/100
  - Completeness: 85/100 (missing optional columns: cell type, developmental stage)
  - Specificity: 60/100 (disease term "cancer" too generic — use specific subtype)
  - Consistency: 90/100 (minor case mismatch in 2 rows)
  - Standards: 55/100 (not using latest template version, missing DIA columns)
```

---

### 12.8 VERSION & CHANGE MANAGEMENT TOOLS

#### `sdrf_diff`
**Purpose**: Compare two versions of an SDRF file and show changes.
**Input**: Two SDRF contents (old, new)
**Output**: Structured diff (added/removed/changed rows, columns, values)
**Why**: Track what changed between annotation rounds or template version upgrades.

#### `sdrf_migrate_template_version`
**Purpose**: Migrate an SDRF from an old template version to a new one.
**Input**: SDRF content, target template version
**Output**: Migrated SDRF with changelog of required changes
**Backend**: Template changelog + column mapping rules
**Why**: When templates update (e.g., v1.0.0 → v1.1.0), existing SDRFs need migration.

```
Example migrations (v1.0.0 → v1.1.0):
  - Add comment[sdrf version] column → "1.1.0"
  - Add comment[sdrf template] column → "NT=ms-proteomics;VV=v1.1.0"
  - Rename "MHC class I" → "MHC-I"
  - Make "characteristics[biological replicate]" required (add if missing)
  - Normalize sample type values
```

#### `sdrf_generate_validation_proof`
**Purpose**: Generate a cryptographic proof that an SDRF passed validation at a specific time.
**Input**: SDRF content, user salt (optional)
**Output**: SHA-512 proof hash with timestamp and validator version
**Backend**: sdrf-pipelines ValidationProof class
**Why**: Reproducible evidence that a file was valid at submission time.

---

### 12.9 MULTI-OMICS & CROSS-REFERENCE TOOLS

#### `sdrf_link_biosamples`
**Purpose**: Cross-reference SDRF samples with BioSamples database entries.
**Input**: SDRF content or PXD accession
**Output**: BioSample accessions linked to each sample, missing linkages
**Why**: BioSamples is the canonical sample registry. Linking enables cross-study comparison.

#### `sdrf_cellosaurus_lookup`
**Purpose**: Validate and enrich cell line metadata from Cellosaurus.
**Input**: Cell line names from SDRF
**Output**: Cellosaurus accession, species, disease, tissue of origin, STR profile, known issues
**Why**: Cell line identity is critical. Cellosaurus catches misidentified lines, contamination, etc.

```
Example:
  Input: "HeLa"
  Output: {
    accession: "CVCL_0030",
    species: "Homo sapiens",
    disease: "cervical adenocarcinoma",
    tissue: "cervix",
    sex: "female",
    age_at_sampling: "30Y",
    known_issues: ["Most widely used human cell line", "HPV-18 positive"],
    str_profile: "D5S818:11,12; D13S317:12,13.3; ..."
  }
```

#### `sdrf_uniprot_organism_check`
**Purpose**: Validate organism names/taxonomy IDs against UniProt reference proteomes.
**Input**: Organism name or NCBI Taxonomy ID
**Output**: UniProt proteome ID, protein count, reference status, common name
**Why**: Ensures the organism has a reference proteome available for database search.

#### `sdrf_multiomics_link`
**Purpose**: Find corresponding transcriptomics/metabolomics datasets for the same study.
**Input**: PXD accession or publication PMID
**Output**: Linked datasets in ArrayExpress, GEO, MetaboLights
**Why**: Multi-omics integration requires linking datasets from the same experiment.

---

### 12.10 EDUCATION & GUIDANCE TOOLS

#### `sdrf_explain_column`
**Purpose**: Explain what a column means, why it's needed, and how to fill it correctly.
**Input**: Column name (e.g., "comment[cleavage agent details]")
**Output**: Definition, format rules, examples, common mistakes, relevant ontologies
**Why**: The specification document is 50+ pages. Users need quick, contextual help.

```
Example:
  Input: "comment[cleavage agent details]"
  Output: {
    definition: "The enzyme used for protein digestion before MS analysis",
    format: "NT=<name>;AC=<MS ontology accession>",
    examples: [
      "NT=Trypsin/P;AC=MS:1001313",
      "NT=Lys-C;AC=MS:1001309"
    ],
    common_mistakes: [
      "Using 'Trypsin' instead of 'Trypsin/P' (Trypsin/P allows cleavage after K/R even before P)",
      "Missing AC= accession",
      "Using UNIMOD accession instead of MS ontology"
    ],
    required: true,
    cardinality: "single (one enzyme per sample)"
  }
```

#### `sdrf_explain_error`
**Purpose**: Given a validation error code/message, explain what went wrong and how to fix it.
**Input**: Error message or error code from sdrf-pipelines
**Output**: Plain-language explanation, root cause, fix instructions, examples
**Backend**: Maps the ~40 ErrorCode enum values to human explanations
**Why**: sdrf-pipelines error messages are technical. Users need "what does this mean and what do I do?"

#### `sdrf_tutorial`
**Purpose**: Generate a step-by-step tutorial for creating an SDRF for a specific experiment type.
**Input**: Experiment type (e.g., "TMT phosphoproteomics in mouse brain")
**Output**: Ordered steps with examples tailored to the experiment
**Why**: Interactive learning — more effective than reading documentation.

#### `sdrf_best_practices`
**Purpose**: Return best practices for a specific experiment type or organism.
**Input**: Experiment type, organism, or specific topic
**Output**: Curated best practices with rationale
**Backend**: Extracted from specification + community experience + error patterns
**Why**: Distills years of community experience into actionable guidance.

---

### 12.11 FILE INTELLIGENCE TOOLS

#### `sdrf_parse_filenames`
**Purpose**: Extract metadata from raw file naming patterns.
**Input**: List of file names from SDRF or PRIDE
**Output**: Detected patterns, extracted metadata (sample ID, fraction, replicate, condition)
**Why**: File names often encode metadata. Extracting it saves manual entry.

```
Example:
  Input: ["Pat01_Tumor_F01_R1.raw", "Pat01_Tumor_F02_R1.raw", "Pat02_Normal_F01_R1.raw"]
  Output: {
    pattern: "{patient}_{condition}_{fraction}_{replicate}.raw",
    extracted: [
      { patient: "Pat01", condition: "Tumor", fraction: "F01", replicate: "R1" },
      { patient: "Pat01", condition: "Tumor", fraction: "F02", replicate: "R1" },
      { patient: "Pat02", condition: "Normal", fraction: "F01", replicate: "R1" }
    ],
    suggested_columns: {
      "characteristics[individual]": ["Pat01", "Pat02"],
      "factor value[disease]": ["Tumor", "Normal"],
      "comment[fraction identifier]": ["1", "2"],
      "comment[technical replicate]": ["1"]
    }
  }
```

#### `sdrf_suggest_source_names`
**Purpose**: Generate meaningful source name identifiers from SDRF metadata.
**Input**: SDRF content (without source names filled in)
**Output**: Suggested source names following community conventions
**Why**: Source names should be unique and meaningful but users struggle with the format.

#### `sdrf_split`
**Purpose**: Split a multi-condition SDRF into separate files per factor value.
**Input**: SDRF content, split attribute(s)
**Output**: Multiple SDRF contents, one per condition
**Backend**: Wraps sdrf-pipelines split-sdrf command
**Why**: Differential expression analysis often requires separate SDRFs per comparison.

#### `sdrf_merge`
**Purpose**: Merge multiple SDRF files into one (with conflict resolution).
**Input**: List of SDRF contents
**Output**: Merged SDRF with conflict report
**Why**: Multi-center studies or reanalysis projects need to combine SDRFs. Currently NO tool supports this.

---

### 12.12 COMMUNITY INTELLIGENCE TOOLS

#### `sdrf_annotation_status`
**Purpose**: Check the annotation status of a PRIDE project in the community collection.
**Input**: PXD accession
**Output**: Status (annotated/not_annotated/in_progress), quality level, last update
**Backend**: Index of multiomics-configs + proteomics-metadata-standard
**Why**: Avoid duplicating work — check if someone already annotated a dataset.

#### `sdrf_community_stats`
**Purpose**: Get aggregate statistics about the SDRF community collection.
**Input**: Optional filters (organism, technology, date range)
**Output**: Statistics (dataset count, sample count, organism distribution, technology distribution, etc.)
**Backend**: Pre-computed from 681 datasets (445K samples)
**Why**: Understand the landscape for grant proposals, reviews, benchmarking.

```
Example:
  Total: 681 datasets, 445,129 samples, 188,307 raw files
  By organism:  Homo sapiens (91.8%), Mus musculus (4.2%), other (4.0%)
  By technology: DDA (90.8%), DIA (5.8%), DDA+DIA (3.4%)
  By label:     label-free (62%), TMT (24%), SILAC (8%), iTRAQ (6%)
  By tissue:    blood/plasma (18%), brain (8%), liver (7%), cell lines (16%)
  Growth:       +120 datasets in last 12 months
```

#### `sdrf_find_gaps`
**Purpose**: Identify under-represented experiment types or organisms in the community collection.
**Input**: None or specific category
**Output**: Gap analysis — what's missing or under-represented
**Why**: Guides community annotation efforts toward high-impact datasets.

---

### 12.13 SEMANTIC SEARCH & SMART QUERY TOOLS

#### `sdrf_smart_search`
**Purpose**: Natural language search across the SDRF ecosystem (datasets, terms, templates, examples).
**Input**: Free-text query
**Output**: Unified results across datasets, ontology terms, templates, publications
**Why**: One search box instead of querying PRIDE, OLS, PubMed, and examples separately.

```
Example:
  Input: "TMT phosphoproteomics mouse brain Alzheimer"
  Output: {
    datasets: [PXD012345 (95% match), PXD023456 (87% match)],
    ontology_terms: {
      disease: "Alzheimer disease (MONDO:0004975)",
      tissue: "brain (UBERON:0000955)",
      modification: "Phospho (UNIMOD:21)"
    },
    templates: ["human", "ms-proteomics"],
    publications: [PMID:12345678, PMID:23456789],
    preprints: [doi:10.1101/2025.01.15.123456]
  }
```

#### `sdrf_ask`
**Purpose**: Answer any question about SDRF format, conventions, or best practices.
**Input**: Natural language question
**Output**: Answer with references to specification, examples, templates
**Backend**: RAG over SDRF specification documents + llms.txt + template YAML
**Why**: The ultimate "help" tool — Claude can answer SDRF questions grounded in the actual spec.

```
Examples:
  "What's the difference between characteristics and factor values?"
  "Can I have multiple instruments in one SDRF?"
  "What ontology should I use for developmental stage?"
  "Is technical replicate required in v1.1.0?"
```

---

### 12.14 INTEGRATION & AUTOMATION TOOLS

#### `sdrf_from_excel`
**Purpose**: Convert an Excel sample sheet to SDRF format.
**Input**: Excel/CSV content with sample metadata
**Output**: SDRF-formatted TSV with column name mapping
**Why**: Researchers often have sample metadata in Excel. This bridges the gap.

#### `sdrf_to_excel`
**Purpose**: Export SDRF to annotated Excel with validation dropdowns.
**Input**: SDRF content, template name
**Output**: Excel file with data validation, conditional formatting, term dropdowns
**Why**: Some collaborators prefer Excel. The export includes validation rules.

#### `sdrf_github_pr_review`
**Purpose**: Review an SDRF file submitted as a GitHub PR (e.g., to multiomics-configs).
**Input**: GitHub PR URL or diff content
**Output**: Structured review with validation, improvement suggestions, approval recommendation
**Why**: Automates the annotation review process for community submissions.

#### `sdrf_webhook_validate`
**Purpose**: Validate an SDRF file and post results to a callback URL (for CI/CD integration).
**Input**: SDRF content, callback URL, template names
**Output**: Validation results posted as structured JSON
**Why**: Enables GitHub Actions, Jenkins, etc. to include SDRF validation in their pipelines.

---

## 13. Complete Tool Inventory (Summary)

| # | Tool | Category | Phase | Template-Aware | Uses Publication |
|---|---|---|---|---|---|
| | **TEMPLATE & SELECTION** | | | | |
| 1 | `sdrf_list_templates` | Template | 1 | core | - |
| 2 | `sdrf_get_template_info` | Template | 1 | core | - |
| 3 | `sdrf_select_templates` | Template | 1 | core | - |
| 4 | `sdrf_detect_template` | Template | 1 | core | optional |
| | **VALIDATION** | | | | |
| 5 | `sdrf_validate` | Validation | 1 | required | - |
| 6 | `sdrf_validate_column` | Validation | 1 | required | - |
| 7 | `sdrf_check_ontology_term` | Validation | 1 | optional | - |
| | **PUBLICATION PIPELINE** | | | | |
| 8 | `sdrf_fetch_project_context` | Publication | 2 | auto-detect | core |
| 9 | `sdrf_search_publication_by_accession` | Publication | 2 | - | core |
| 10 | `sdrf_extract_metadata_from_paper` | Publication | 2 | uses for mapping | core |
| 11 | `sdrf_enrich_from_mesh` | Publication | 2 | uses for mapping | core |
| | **ANNOTATION** | | | | |
| 12 | `sdrf_create_from_pride` | Annotation | 2 | required | enriched |
| 13 | `sdrf_create_from_publication` | Annotation | 2 | required | core |
| 14 | `sdrf_annotate_column` | Annotation | 2 | required | - |
| 15 | `sdrf_suggest_factor_values` | Annotation | 2 | required | optional |
| 16 | `sdrf_fill_technical_columns` | Annotation | 2 | required | - |
| | **ONTOLOGY** | | | | |
| 17 | `sdrf_ontology_column_mapping` | Ontology | 1 | required | - |
| 18 | `sdrf_ontology_navigate` | Ontology | 2 | optional | - |
| 19 | `sdrf_cross_ontology_map` | Ontology | 3 | - | - |
| 20 | `sdrf_validate_term_specificity` | Ontology | 3 | required | - |
| | **RECOMMENDATION** | | | | |
| 21 | `sdrf_recommend_terms` | Recommendation | 2 | required | - |
| 22 | `sdrf_suggest_improvements` | Recommendation | 3 | required | optional |
| 23 | `sdrf_fix_common_errors` | Recommendation | 3 | optional | - |
| | **ANALYSIS & DESIGN** | | | | |
| 24 | `sdrf_analyze_experimental_design` | Analysis | 3 | optional | optional |
| 25 | `sdrf_brainstorm_metadata` | Analysis | 3 | required | optional |
| 26 | `sdrf_compare_datasets` | Analysis | 4 | optional | - |
| 27 | `sdrf_literature_context` | Analysis | 4 | - | core |
| 28 | `sdrf_detect_batch_effects` | Design Intel | 3 | - | - |
| 29 | `sdrf_detect_confounders` | Design Intel | 3 | - | - |
| 30 | `sdrf_assess_replication` | Design Intel | 3 | - | - |
| 31 | `sdrf_suggest_comparisons` | Design Intel | 3 | - | - |
| | **PIPELINE INTEGRATION** | | | | |
| 32 | `sdrf_convert` | Pipeline | 2 | required | - |
| 33 | `sdrf_recommend_pipeline` | Pipeline | 3 | required | - |
| 34 | `sdrf_check_pipeline_compatibility` | Pipeline | 3 | required | - |
| 35 | `sdrf_generate_quantms_config` | Pipeline | 3 | required | - |
| | **RAW FILE INTELLIGENCE** | | | | |
| 36 | `sdrf_detect_parameters` | Raw File | 3 | - | - |
| 37 | `sdrf_compare_declared_vs_detected` | Raw File | 3 | - | - |
| 38 | `sdrf_detect_ptms` | Raw File | 3 | - | - |
| | **DATA CLEANING** | | | | |
| 39 | `sdrf_normalize_values` | Cleaning | 2 | required | - |
| 40 | `sdrf_standardize_modifications` | Cleaning | 2 | - | - |
| 41 | `sdrf_deduplicate_rows` | Cleaning | 2 | - | - |
| 42 | `sdrf_validate_file_references` | Cleaning | 3 | - | - |
| | **CROSS-DATASET INTELLIGENCE** | | | | |
| 43 | `sdrf_search_examples` | Cross-Dataset | 4 | optional | - |
| 44 | `sdrf_find_similar_experiments` | Cross-Dataset | 4 | optional | - |
| 45 | `sdrf_term_usage_stats` | Cross-Dataset | 2 | optional | - |
| 46 | `sdrf_column_completeness_report` | Cross-Dataset | 3 | required | - |
| 47 | `sdrf_trending_terms` | Cross-Dataset | 4 | - | - |
| | **COMPLIANCE & REPORTING** | | | | |
| 48 | `sdrf_miape_compliance` | Compliance | 3 | required | optional |
| 49 | `sdrf_generate_submission_report` | Compliance | 3 | optional | enriched |
| 50 | `sdrf_generate_methods_section` | Compliance | 3 | - | enriched |
| 51 | `sdrf_quality_score` | Compliance | 2 | required | - |
| | **VERSIONING** | | | | |
| 52 | `sdrf_diff` | Versioning | 2 | - | - |
| 53 | `sdrf_migrate_template_version` | Versioning | 3 | core | - |
| 54 | `sdrf_generate_validation_proof` | Versioning | 2 | required | - |
| | **MULTI-OMICS & CROSS-REF** | | | | |
| 55 | `sdrf_link_biosamples` | Multi-omics | 4 | - | - |
| 56 | `sdrf_cellosaurus_lookup` | Multi-omics | 2 | optional | - |
| 57 | `sdrf_uniprot_organism_check` | Multi-omics | 2 | - | - |
| 58 | `sdrf_multiomics_link` | Multi-omics | 4 | - | enriched |
| | **EDUCATION** | | | | |
| 59 | `sdrf_explain_column` | Education | 1 | required | - |
| 60 | `sdrf_explain_error` | Education | 1 | optional | - |
| 61 | `sdrf_tutorial` | Education | 3 | required | - |
| 62 | `sdrf_best_practices` | Education | 3 | required | - |
| | **FILE INTELLIGENCE** | | | | |
| 63 | `sdrf_parse_filenames` | File Intel | 2 | - | - |
| 64 | `sdrf_suggest_source_names` | File Intel | 2 | - | - |
| 65 | `sdrf_split` | File Intel | 2 | - | - |
| 66 | `sdrf_merge` | File Intel | 3 | - | - |
| | **COMMUNITY** | | | | |
| 67 | `sdrf_annotation_status` | Community | 2 | - | - |
| 68 | `sdrf_community_stats` | Community | 4 | - | - |
| 69 | `sdrf_find_gaps` | Community | 4 | - | - |
| | **SEARCH** | | | | |
| 70 | `sdrf_smart_search` | Search | 3 | optional | optional |
| 71 | `sdrf_ask` | Search | 3 | optional | - |
| | **INTEGRATION** | | | | |
| 72 | `sdrf_from_excel` | Integration | 2 | required | - |
| 73 | `sdrf_to_excel` | Integration | 3 | required | - |
| 74 | `sdrf_github_pr_review` | Integration | 4 | required | - |
| 75 | `sdrf_webhook_validate` | Integration | 4 | required | - |
| | **DISCOVERY** | | | | |
| 76 | `sdrf_search_pride_projects` | Discovery | 2 | - | - |
| 77 | `sdrf_get_publication_metadata` | Discovery | 2 | - | core |

**Legend:**
- **Template-Aware**: `core` = template tool itself, `required` = templates parameter needed, `optional` = works better with templates, `-` = not template-related
- **Uses Publication**: `core` = publication tool itself, `enriched` = better output with publication data, `optional` = can use publication context, `-` = independent

---

## 14. Revised Implementation Phases

### Phase 1: Foundation (MVP) — 11 tools
Template engine + core validation + ontology mapping + education.
Tools: 1-7, 17, 59-60 + basic SDRF parsing

### Phase 2: Annotation + Publication Pipeline — 24 tools
PRIDE integration, publication retrieval chain, term mapping, file parsing, quality scoring.
Tools: 8-16, 18, 21, 32, 39-41, 45, 51-52, 54, 56-57, 63-65, 67, 72, 76-77

### Phase 3: Intelligence — 21 tools
Design analysis, auto-fix, brainstorm, conversion intelligence, raw file detection.
Tools: 19-20, 22-31, 33-38, 42, 46, 48-50, 53, 61-62, 66, 70-71, 73

### Phase 4: Discovery & Community — 11 tools
Cross-dataset search, literature, multi-omics, community tools, CI/CD.
Tools: 26-27, 43-44, 47, 55, 58, 68-69, 74-75

---

## 15. Open Questions

- Should the plugin also support SDRF for other omics (transcriptomics, metabolomics) or focus on proteomics?
- How to handle large SDRF files (10,000+ rows) within MCP message limits?
- Should the term dictionary be versioned and auto-updated?
- Integration with sdrfedit (web editor) — should the plugin be usable from the editor's AI panel?
- Authentication for PRIDE API (currently public, but rate-limited)?
- Should we support offline mode (no OLS/PRIDE access)?
- Should `sdrf_ask` use RAG with embedded spec documents or rely on Claude's training data + MCP resources?
- How deep should the techsdrf integration go? (requires raw file download infrastructure)
- Should the plugin expose MCP prompts (pre-built conversation starters) in addition to tools?
