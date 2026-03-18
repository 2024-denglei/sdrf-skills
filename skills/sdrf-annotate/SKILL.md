---
name: sdrf:annotate
description: Use when the user wants to create or annotate an SDRF file for a proteomics dataset. Triggers on PXD accessions, requests to create SDRF, or annotation tasks.
user-invocable: true
argument-hint: "[PXD accession or experiment description]"
---

# SDRF Annotation Workflow

You are performing a complete SDRF annotation. Follow these steps IN ORDER.
Do not skip steps. Do not guess — use MCP tools to verify everything.

## Step 1: Gather Project Context

If a **PXD accession** is provided:

### 1.1 Get PRIDE project metadata
```
Tool: get_project_details(project_accession="PXD######")
Extract: organism, instruments, modifications, publications (PMID/DOI), file count, description
```

### 1.2 Get the file list
```
Tool: get_project_files(project_accession="PXD######")
Extract: raw file names (for comment[data file]), file count, file types
```

### 1.3 Find and read the publication
```
a. Extract PMID or DOI from PRIDE response (publications field)
b. If PMID → get_article_metadata(pmids=["PMID"])
c. Convert to PMC ID → convert_article_ids(ids=["PMID"], id_type="pmid")
d. If PMC ID exists → get_full_text_article(pmc_ids=["PMC_ID"])
   Focus on: Methods section, sample descriptions, Table 1 (demographics)
e. If NO PMID in PRIDE → search_europepmc(query="PXD######")
   This searches EuropePMC for papers mentioning the accession.
f. If DOI but no PMID → convert_article_ids(ids=["DOI"], id_type="doi")
g. If only preprint → search_preprints() with title keywords from PRIDE
```

### 1.4 Extract sample metadata from the paper
Read the paper systematically and extract:
- How many samples? How many conditions/groups?
- Tissues/cell types per group
- Patient demographics (age, sex, ancestry) if available
- Experimental conditions (treatment, disease state, time points)
- Labeling strategy (which TMT/iTRAQ channels for which samples)
- Fractionation details (number of fractions, method)
- Instrument and acquisition method details
- Modifications searched

If **no PXD** but an experiment description, skip to Step 2.

## Step 2: Select Templates

Use the sdrf:templates decision tree. Based on the gathered context:

1. **Technology**: MS → `ms-proteomics`. Affinity → `affinity-proteomics`
2. **Organism**: Human → `human`. Mouse/rat → `vertebrates`. Drosophila → `invertebrates`. Plant → `plants`. Microbiome → `metaproteomics` + child
3. **Experiment type**: DIA → `+ dia-acquisition`. Cell lines → `+ cell-lines`. Single-cell → `+ single-cell`. XL-MS → `+ crosslinking`. Immunopeptidome → `+ immunopeptidomics`
4. **Clinical/Oncology**: Patient study → `+ clinical-metadata`. Cancer → `+ oncology-metadata`

Present the template selection to the user for confirmation before proceeding.
Explain WHY each template was chosen and what columns it adds.

## Step 3: Build the SDRF Structure

Determine the columns to include based on the selected templates:

1. **Read `spec/sdrf-proteomics/TERMS.tsv`** — filter rows where `usage` contains each selected template name
2. **Read individual template YAMLs** at `spec/sdrf-proteomics/sdrf-templates/{name}/{version}/{name}.yaml` for requirement levels
3. Merge all columns from all selected templates (union of all template column sets)

Organize columns in this order:

**Anchor columns:**
1. `source name`

**Characteristics columns (sample metadata):**
- All `characteristics[...]` columns from TERMS.tsv for the selected templates
- Order: organism, organism part, disease, cell type, material type, then template-specific (age, sex, cell line, etc.), then biological replicate

**Anchor + technology:**
- `assay name`
- `technology type`

**Comment columns (technical metadata):**
- All `comment[...]` columns from TERMS.tsv for the selected templates
- Order: instrument, label, modification parameters (one per mod), cleavage agent details, acquisition method, dissociation method, collision energy, tolerances, template-specific (scan windows for DIA, etc.), fraction identifier, technical replicate, data file

**Factor values:**
- `factor value[<variable>]`

**SDRF metadata:**
- `comment[sdrf version]` (value: `v1.1.0`)
- `comment[sdrf template]` (one column per template, format: `NT=template_name;VV=vX.Y.Z`)

## Step 4: Fill Sample Metadata

For EACH unique value that goes into a characteristics column:

### 4.1 Search OLS for the correct ontology term
```
Use: searchClasses(query="breast carcinoma", ontologyId="mondo")
Or: search(query="Homo sapiens")
```

### 4.2 Verify the term is from the CORRECT ontology
Read TERMS.tsv `values` field for the column to determine which ontology(ies) to search:
- organism → NCBITaxon
- organism part → UBERON (primary), BTO (fallback)
- disease → MONDO (primary), EFO, DOID
- cell type → CL (primary), BTO, CLO
- cell line → CLO, BTO, EFO (+ Cellosaurus for accession)
- instrument → MS, PRIDE
- modifications → UNIMOD

### 4.3 Check specificity
- "cancer" → too generic, use "breast carcinoma" or specific subtype
- "tissue" → too generic, use "liver" or "temporal cortex"
- "cell" → too generic, use "T cell" or "epithelial cell"
- Use getChildren() to see if there's a more specific child term

### 4.4 Use reserved words correctly
- `not available` — information exists but was not provided
- `not applicable` — property doesn't apply to this sample
- `normal` — healthy control (for disease column, use with PATO:0000461)
- NEVER use "N/A", "NA", "unknown", "none"
- Check TERMS.tsv `allow_not_available`, `allow_not_applicable`, `allow_pooled` for each column

## Step 5: Fill Technical Metadata

### 5.1 Instrument
```
searchClasses(query="Q Exactive", ontologyId="ms")
Format in SDRF: AC=MS:1001911;NT=Q Exactive HF
```

### 5.2 Modifications — CRITICAL
Use EXACT UNIMOD accessions. Common setup:
```
Column 1: NT=Carbamidomethyl;AC=UNIMOD:4;TA=C;MT=Fixed
Column 2: NT=Oxidation;AC=UNIMOD:35;TA=M;MT=Variable
Column 3: NT=Acetyl;AC=UNIMOD:1;PP=Protein N-term;MT=Variable
```
**Double-check**: UNIMOD:1 = Acetyl, UNIMOD:21 = Phospho. Most common swap!
For TMT: UNIMOD:737 (TMT6/10/11plex) or UNIMOD:2016 (TMTpro 16/18plex)

### 5.3 Cleavage agent
```
searchClasses(query="Trypsin", ontologyId="ms")
Format: NT=Trypsin;AC=MS:1001251
```

### 5.4 Labels
- Label-free: `label free sample`
- TMT: `TMT126`, `TMT127N`, `TMT127C`, etc. (one row per channel per file)
- SILAC: `SILAC light`, `SILAC heavy`

### 5.5 Acquisition method
Use PRIDE ontology terms:
- `Data-Dependent Acquisition`
- `Data-Independent Acquisition`

## Step 6: Map Files to Samples

- Get file names from Step 1.2 (PRIDE file list)
- Each raw file → 1 row (label-free) or N rows (N = label channels for TMT/SILAC)
- Match files to samples using naming patterns from the paper or PRIDE description
- Set `comment[fraction identifier]` from file naming patterns (1 if not fractionated)
- Set `comment[technical replicate]` starting from 1

**Row count formula:**
```
Total rows = samples × fractions × label_channels × technical_replicates
```

## Step 7: Set Factor Values

1. Identify what is being compared (disease vs control? treatment vs untreated?)
2. Create `factor value[<variable>]` column (e.g., `factor value[disease]`)
3. Copy values from the corresponding characteristics column
4. If multiple factors → create multiple factor value columns

## Step 8: Add SDRF Metadata

- `comment[sdrf version]` → `v1.1.0`
- `comment[sdrf template]` → one column per template: `NT=ms-proteomics;VV=v1.1.0`
- `comment[sdrf annotation tool]` → `manual curation` (or tool name if applicable)

## Step 9: Present and Validate

Present the completed SDRF as a TSV code block and explain:
- Total rows and columns
- Sample groups and counts per group
- Templates applied (with version)
- File mapping summary
- Any values marked as `not available` (ask user to fill)
- Any values you're uncertain about (flag for user review)
- Suggest running `sdrf-pipelines validate-sdrf` for programmatic validation

## Important Rules

- NEVER fabricate ontology accessions — always search OLS
- NEVER guess file names — get them from PRIDE file list
- NEVER invent sample information not found in the paper or PRIDE metadata
- If information is missing from the paper, mark as `not available` and tell the user
- Always clearly distinguish: extracted from paper vs inferred vs assumed
- Present the SDRF as a TSV code block for easy copy-paste
- Multiple `comment[modification parameters]` columns are normal (one per mod)
- Multiple `comment[sdrf template]` columns are normal (one per template)
