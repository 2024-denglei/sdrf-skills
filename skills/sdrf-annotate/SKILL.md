---
name: sdrf:annotate
description: Use when the user wants to create or annotate an SDRF file for a proteomics dataset. Triggers on PXD accessions, requests to create SDRF, or annotation tasks.
user-invocable: true
argument-hint: "[PXD accession or experiment description]"
---

# SDRF Annotation Workflow

You are performing a complete SDRF annotation. Follow these steps IN ORDER.
Do not skip steps. Do not guess — use MCP tools to verify everything.

## Step 0: Check parse_sdrf availability

Before starting, verify that `parse_sdrf` is available (run `parse_sdrf --version` or `which parse_sdrf`). If it is not installed:
- Inform the user that programmatic validation will be skipped
- Suggest `/sdrf:setup` or `conda env create -f environment.yml && conda activate sdrf-skills` (or `pip install -r requirements.txt`)
- Offer to continue with manual checks only, or wait for the user to install and retry

## Step 1: Gather Project Context

If a **PXD accession** is provided:

### 1.1 Get PRIDE project metadata
```text
Tool: get_project_details(project_accession="PXD######")
Extract: organism, instruments, modifications, publications (PMID/DOI), file count, description
```

### 1.2 Get the file list
```text
Tool: get_project_files(project_accession="PXD######")
Extract: raw file names (for comment[data file]), file count, file types
```

If MCP access is unavailable or incomplete, prefer the PRIDE Archive REST fallback:
```text
GET https://www.ebi.ac.uk/pride/ws/archive/v3/projects/PXD######/files/all
```
Use this endpoint to retrieve the complete file list for the project in one call.
It is the preferred REST path for counting files, checking raw-file coverage, and
building `comment[data file]` values during annotation.
If this endpoint returns `0` files for a valid PXD hosted through
`PanoramaPublic`, `MassIVE`, `iProX`, or `jPOST`, treat that as
`archive endpoint empty for external repository` rather than `no data`.
For MassIVE-backed datasets, use the helper script in this repo to recover raw
file names from ProteomeCentral + MassIVE JSON + MassIVE FTP:
```text
python scripts/massive_raw_files.py PXD016117 --mode raw
python scripts/massive_raw_files.py PXD016117 --mode acquisition --format tsv
```
This is the preferred fallback when you need `comment[data file]` values for a
MassIVE-hosted PXD and PRIDE does not expose the archive file list.
Also inspect companion files under MassIVE `other/` or supplementary dataset
attachments. In practice these often contain the curator key you need for TMT
channel-to-sample mapping, pooled-reference channels, blanks, longitudinal
timepoints, or cohort aliases that are not recoverable from PRIDE metadata
alone.

### 1.3 Find and read the publication
```text
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
- Developmental stage when the cohort is clearly adult, pediatric, fetal, juvenile, etc.
- Experimental conditions (treatment, disease state, time points)
- Labeling strategy (which TMT/iTRAQ channels for which samples)
- Fractionation details (number of fractions, method)
- Instrument and acquisition method details
- Modifications searched

Demographic evidence rules:
- `characteristics[developmental stage]` can be added from cohort-level evidence when the whole analyzed cohort is clearly in one stage, for example all subjects are adults or the study is explicitly pediatric.
- `characteristics[age]`, `characteristics[sex]`, and `characteristics[ethnicity]` should be added only when they can be mapped to individual source samples or a per-sample supplementary table.
- If the paper reports only group summaries such as median age, percent male, or ethnicity distribution, keep those fields out of per-sample SDRF rows and mention the limitation in the notes.

### 1.4b Map PRIDE source samples to ENA/BioSamples when possible
For datasets with paired ENA/SRA/BioSamples records, especially metaproteomics studies:

- Treat BioSample accessions as **source-sample identifiers**, not raw-file identifiers
- A repeated BioSample accession across many SDRF rows is correct when those rows share the same `source name`
- Do **not** assume one BioSample per raw file, fraction, or technical replicate

Use this mapping order:

1. Prefer **exact study-linked lookups** in ENA or BioSamples:
   - ENA sample search by study/BioProject accession
   - BioSamples exact filters on project/study accessions
2. Compare the returned sample metadata against the paper and PRIDE:
   - collection date
   - geographic location / coordinates
   - isolation source / environmental medium
   - sample title / alias
   - whether the study describes one shared source sample or multiple distinct source samples
3. Add `characteristics[biosample accession number]` only when:
   - the PRIDE `source name` clearly maps to a deposited ENA/BioSamples sample, or
   - there is one well-supported shared source sample that all assay rows derive from

Avoid this failure mode:

- BioSamples UI free-text search can return unrelated accessions through fuzzy matching
- Treat UI text-search hits as **leads only**, not evidence
- Confirm project membership with exact ENA/BioSamples study-linked queries before annotating

Metaproteomics rule of thumb:

- if all rows in one SDRF share one `source name`, one `biological replicate`, and differ only by fraction / technical replicate / workflow, repeating one BioSample accession across those rows is usually the correct representation
- if the paper describes multiple distributed aliquots from one shared environmental source sample, a single repeated BioSample accession may still be appropriate if the external record clearly represents that shared source sample

### 1.5 Guard plasma campaigns against false positives
If the user is targeting blood-plasma projects:
- default to `Homo sapiens` unless the user explicitly requests animal studies
- confirm species with PRIDE `organisms` first
- if PRIDE species is incomplete, use the linked paper to confirm that the plasma cohort is human-only before promotion
- keep mouse, rat, or mixed-species plasma projects as audit-only candidates until the user asks for them
- expand the disease through OLS before PRIDE discovery:
  - lexical OLS first in `MONDO`, `DOID`, `EFO`, and `NCIT`
  - add useful synonyms and preferred labels
  - use OLS embeddings for broad disease names when subtype phrasing is likely in PRIDE, for example `kidney tumor` -> renal cancer variants
  - keep in-scope child terms when biomarker studies use the subtype rather than the parent label, for example `myositis` -> `dermatomyositis`, `sarcoma` -> `Ewing sarcoma`, `myeloma` -> `multiple myeloma`, or `alcohol-related liver disease` -> `alcoholic hepatitis`
  - for influenza-like campaigns, acceptable widening can include `influenza A`, `IAV`, `H1N1`, `flu`, and, if explicitly allowed by the user, broader `viral pneumonia` plus `serum`
  - tag each promoted candidate as an `exact`, `child_term`, `related`, or `surrogate` disease match so later ranking is honest about coverage strength
- classify the project workflow from PRIDE before prioritizing it:
  - read `experimentTypes` for acquisition style like `Data-independent acquisition`, `Data-dependent acquisition`, or `Gel-based experiment`
  - read `quantificationMethods` for explicit quant style like `TMT`, `iTRAQ`, `label-free quantification`, `Dimethyl Labeling`, or `NSAF`
  - if those fields are incomplete, inspect `sampleProcessingProtocol`, `dataProcessingProtocol`, keywords, and the manuscript methods section for explicit `TMT`, `iTRAQ`, `LFQ`, `DIA`, `SWATH`, `MaxQuant`, or `Spectronaut` wording
  - keep separate `acquisition_mode` and `quant_mode` annotations rather than collapsing everything into one label
- treat `blood plasma`, `plasma proteome`, `plasma samples`, and `plasma extracellular vesicles` as valid plasma-sample signals
- do NOT treat `plasma cells` or `plasma membrane` as blood-plasma sample signals
- for the current plasma-dataset campaigns, only promote datasets hosted by `PRIDE`, `MassIVE`, `jPOST`, or `iProX`; keep `PanoramaPublic` hits as audit-only candidates for now
- for automatic discovery or ranking, only shortlist accessions when plasma context is present (`positive` or `ambiguous`) and the disease is explicit in the title, description, or linked paper
- keep `plasma_context=missing` disease hits as audit-only candidates until manuscript or PRIDE evidence confirms a real blood-plasma sample
- if a candidate dataset lacks usable raw or acquisition files, do not promote it into the active annotation set even if the disease and matrix match
- when a manuscript is available, classify the accession before annotation:
  - `confirmed_plasma` if plasma is explicit in title, abstract, methods, results, or supplementary text
  - `mixed_includes_plasma` if plasma is explicit but the study also includes CSF, serum, tissue, urine, or cell-line material
  - `likely_non_plasma` if the manuscript points to a different primary matrix such as CSF, platelet releasate, urine, BALF, or cell-line material
  - `unclear` if the paper cannot confirm plasma; do not auto-promote these datasets into a plasma campaign
- if the accession is already present in the local plasma collection, refine the existing SDRF instead of creating a duplicate target

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
- Order: organism, organism part, disease, cell type, material type, then template-specific (developmental stage, age, sex, cell line, etc.), then biological replicate

**Anchor + technology:**
- `assay name`
- `technology type`

**Comment columns (technical metadata):**
- All `comment[...]` columns from TERMS.tsv for the selected templates
- Order: instrument, label, modification parameters (one per mod), cleavage agent details, acquisition method, dissociation method, collision energy, tolerances, template-specific (scan windows for DIA, etc.), fraction identifier, technical replicate, data file

**Factor values:**
- `factor value[<variable>]`

**SDRF metadata:**
- `comment[sdrf version]` (read the current version from `spec/sdrf-proteomics/sdrf-templates/templates.yaml`)
- `comment[sdrf template]` (one column per template, format: `NT=template_name;VV=vX.Y.Z`)

## Step 4: Fill Sample Metadata

Before filling demographic fields, decide whether the paper supports:
- cohort-level demographic context only
- or true sample-level demographic assignment

Use this rule:
- `developmental stage` may come from cohort-level manuscript evidence if the full analyzed cohort is unambiguously adult, pediatric, fetal, juvenile, and so on
- `age`, `sex`, and `ethnicity` require source-sample or individual-level mapping
- if only cohort summaries exist, leave per-sample demographic fields as missing / omitted rather than guessing

For EACH unique value that goes into a characteristics column:

### 4.1 Normalize a short mention first
- If the value already comes from PRIDE metadata or an existing SDRF cell, clean that value and use it directly.
- If the value comes from a manuscript, first extract the shortest standalone entity phrase and keep the sentence only as evidence.
- Search the expanded form before the abbreviation when both are available.
- Do NOT send full manuscript sentences to OLS or ZOOMA unless you are debugging a failed lookup.

### 4.2 Search OLS lexically first
```text
Use: searchClasses(query="breast carcinoma", ontologyId="mondo")
Or: search(query="Homo sapiens")
```
For clean SDRF-like values, lexical exact or synonym matches are the default path and usually outperform embeddings.

### 4.3 Use embeddings and ZOOMA only when needed
Trigger OLS embedding search when:
- lexical search returns no result
- the mention is abbreviation-like (`HCC`, `PDAC`, `GBM`, `TNBC`)
- the top lexical hits are conflicting or clearly over-specific
- the mention came from noisy manuscript text rather than a curated label

Use the OLS MCP tools in this order:
```text
1. listEmbeddingModels()
2. searchClassesWithEmbeddingModel(query="<clean phrase>", ontologyId="<ontology>", model="<embed model>")
3. If ontology-specific search is unavailable, use searchWithEmbeddingModel() and filter manually
```

Use ZOOMA as a slower fallback for manuscript-derived free text or when lexical and embedding results still disagree:
```text
GET https://www.ebi.ac.uk/spot/zooma/v2/api/services/annotate?propertyValue=<clean phrase>&propertyType=<field>
```
- Accept only `HIGH` or `GOOD` confidence mappings from ZOOMA
- Always verify returned `semanticTags` in OLS and confirm the ontology is allowed by `TERMS.tsv`
- Use ZOOMA mainly for disease, phenotype, treatment, or other curator-style phrases backed by prior curation

Field defaults:
- `organism`, `cell line` → lexical first, fallback methods rarely needed
- `organism part`, `cell type`, `treatment` → lexical first, embeddings/ZOOMA only if lexical is weak
- `disease`, `phenotype` → lexical first, embeddings and ZOOMA are useful fallbacks

### 4.4 Verify the term is from the CORRECT ontology
Read TERMS.tsv `values` field for the column to determine which ontology(ies) to search:
- organism → NCBITaxon
- organism part → UBERON (primary), BTO (fallback)
- disease → MONDO (primary), EFO, DOID
- cell type → CL (primary), BTO, CLO
- cell line → CLO, BTO, EFO (+ Cellosaurus for accession)
- instrument → MS, PRIDE
- modifications → UNIMOD
- biosample accession number → exact BioSample accession from ENA/BioSamples only; do not infer from fuzzy search alone

For organisms, prefer the current NCBITaxon label over legacy synonyms when validation fails on an older name.
Crosslinking cleanup examples that should be normalized before final validation:
- `chaetomium thermophilum` → `thermochaetoides thermophila`
- `chlorobium tepidum` → `chlorobaculum tepidum`
- `canis familiaris` → `canis lupus familiaris`
- `deinococcus radiodurans r1` → `deinococcus radiodurans`

For crosslinking-specific assay cleanup, use explicit file-name evidence when the SDRF still says `NT=unknown crosslinker;AC=XLMOD:00000`. Safe examples seen in sandbox cleanup:
- file names containing `DSSO` → `NT=DSSO;AC=XLMOD:02010;CL=yes;TA=K,S,T,Y,nterm;MH=54.01;ML=85.98`
- file names containing `BS3` → `NT=BS3;AC=XLMOD:02000`
- file names containing `TurboID` → `NT=TurboID;AC=XLMOD:02251`
- file names containing `iQPIR`, `BDP`, or `d8BDP` → `NT=PIR;AC=XLMOD:02014`

After recovering a known cross-linker, backfill `characteristics[crosslink distance]` when the template guidance is explicit:
- `BS3` / `DSS` → `30 Å`
- `DSSO` → `26.4 Å`
- `EDC` → `11.4 Å`
- `formaldehyde` → `2 Å`
- `DSBU` / `DSBSO` → `26.4 Å`
- `SDA` / `sulfo-SDA` → `18 Å`

For `comment[crosslink enrichment method]`, use explicit separation tokens from `comment[data file]` when the field is still missing:
- `SCX` → `strong cation exchange chromatography`
- `SEC` → `size exclusion chromatography`
- `FAIMS` → `FAIMS`
- dataset title containing `streptavidin pull-down` → `streptavidin pull-down`
- dataset title containing `IMAC-enrichable` → `immobilized metal affinity chromatography`
- dataset title containing `CuAAC-enrichable` → `CuAAC enrichment`

When one of those enrichment-method values is recovered and `characteristics[enrichment process]` is still missing, backfill `enrichment of cross-linked peptides`.

### 4.5 Check specificity
- "cancer" → too generic, use "breast carcinoma" or specific subtype
- "tissue" → too generic, use "liver" or "temporal cortex"
- "cell" → too generic, use "T cell" or "epithelial cell"
- Use getChildren() to see if there's a more specific child term
- If embeddings or ZOOMA suggest a child term that is more specific than the paper text supports, prefer the broader lexical term and note the ambiguity

### 4.6 Use reserved words correctly
- `not available` — information exists but was not provided
- `not applicable` — property doesn't apply to this sample
- `normal` — healthy control (for disease column, use with PATO:0000461)
- NEVER use "N/A", "NA", "unknown", "none"
- Check TERMS.tsv `allow_not_available`, `allow_not_applicable`, `allow_pooled` for each column

## Step 5: Fill Technical Metadata

### 5.1 Instrument
```text
searchClasses(query="Q Exactive", ontologyId="ms")
Format in SDRF: AC=MS:1001911;NT=Q Exactive HF
```

If validation complains about an instrument term that is also documented in the
official PSI-MS / ProteomeXchange schema, verify the accession first instead of
rewriting the instrument blindly. Example: `LTQ Orbitrap Elite` with
`MS:1001910` may warn in some validator/cache combinations even though the term
is publicly documented.

### 5.2 Modifications — CRITICAL
Use EXACT UNIMOD accessions. Common setup:
```text
Column 1: NT=Carbamidomethyl;AC=UNIMOD:4;TA=C;MT=Fixed
Column 2: NT=Oxidation;AC=UNIMOD:35;TA=M;MT=Variable
Column 3: NT=Acetyl;AC=UNIMOD:1;PP=Protein N-term;MT=Variable
```
**Double-check**: UNIMOD:1 = Acetyl, UNIMOD:21 = Phospho. Most common swap!
For TMT: UNIMOD:737 (TMT6/10/11plex) or UNIMOD:2016 (TMTpro 16/18plex)

### 5.3 Cleavage agent
```text
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

### 5.6 Verify technical metadata with raw file analysis (recommended)
If the dataset has raw files available (PRIDE or local), recommend using **techsdrf**
to verify and refine the technical metadata filled in Steps 5.1–5.5:
```text
Run /sdrf:techrefine PXD###### to verify instrument, tolerances, modifications,
and DDA/DIA classification directly from the raw MS files.
```
techsdrf can detect discrepancies between what's declared in the paper/PRIDE and
what's actually in the raw data — especially for instrument model specificity,
mass tolerances, and undeclared or incorrect modifications.

## Step 6: Map Files to Samples

- Get file names from Step 1.2 (PRIDE file list)
- Each raw file → 1 row (label-free) or N rows (N = label channels for TMT/SILAC)
- Match files to samples using naming patterns from the paper or PRIDE description
- Set `comment[fraction identifier]` from file naming patterns (1 if not fractionated)
- Set `comment[technical replicate]` starting from 1

**Row count formula:**
```text
Total rows = samples × fractions × label_channels × technical_replicates
```

## Step 7: Set Factor Values

1. Identify what is being compared (disease vs control? treatment vs untreated?)
2. Create `factor value[<variable>]` column (e.g., `factor value[disease]`)
3. Copy values from the corresponding characteristics column
4. If multiple factors → create multiple factor value columns

## Step 8: Add SDRF Metadata

- `comment[sdrf version]` → read latest version from `spec/sdrf-proteomics/sdrf-templates/templates.yaml`
- `comment[sdrf template]` → one column per template: `NT={template_name};VV=v{version}` (versions from templates.yaml)
- `comment[sdrf annotation tool]` → `manual curation` (or tool name if applicable)

## Step 9: Validate with sdrf-pipelines

Before presenting the SDRF to the user, **always** run programmatic validation
with `sdrf-pipelines`. This catches errors that manual review misses.

### 9.1 Update spec to latest version
```bash
git submodule update --remote --recursive
```

### 9.2 Save the SDRF to a temporary file
Write the completed SDRF to a `.sdrf.tsv` file so `parse_sdrf` can validate it.

### 9.3 Run validation with detected templates
```bash
parse_sdrf validate-sdrf \
  --sdrf_file output.sdrf.tsv \
  --template <template1> \
  --template <template2>
```
Use the templates selected in Step 2. For example, a human DIA study:
```bash
parse_sdrf validate-sdrf \
  --sdrf_file output.sdrf.tsv \
  --template ms-proteomics \
  --template human \
  --template dia-acquisition
```

If `parse_sdrf` is not installed, tell the user:
```text
Install sdrf-pipelines to enable automatic validation:
  pip install sdrf-pipelines
```

### 9.4 Fix any validation errors
If `parse_sdrf` reports errors:
1. Fix each error in the SDRF
2. Re-run validation until it passes
3. Only proceed to Step 10 when validation is clean (or only warnings remain)

## Step 10: Present Results

Present the validated SDRF as a TSV code block and explain:
- Total rows and columns
- Sample groups and counts per group
- Templates applied (with version)
- File mapping summary
- Validation result (PASS / warnings)
- Any values marked as `not available` (ask user to fill)
- Any values you're uncertain about (flag for user review)

## Step 11: Recommend Community Contribution

If the annotation was for a **ProteomeXchange dataset** (PXD accession):

1. Check if this PXD already exists in `spec/annotated-projects/{PXD}/`
2. Tell the user their annotation can be contributed to the community:

```text
Your SDRF annotation for {PXD} is ready!

The proteomics-sample-metadata community repository collects annotated SDRF files
for ProteomeXchange datasets. Contributing your annotation means:
  - Other researchers can reuse your metadata
  - Analysis pipelines (quantms) can automatically reprocess the dataset
  - The annotation becomes part of the PRIDE SDRF Explorer

Run /sdrf:contribute {PXD} to create a PR, or see the commands to do it manually.
```

3. If the PXD already exists in annotated-projects/, mention this is an update to an existing annotation

This step is a recommendation only — do not force the user to contribute.

## Important Rules

- NEVER fabricate ontology accessions — always search OLS
- NEVER guess file names — get them from PRIDE file list
- NEVER invent sample information not found in the paper or PRIDE metadata
- If information is missing from the paper, mark as `not available` and tell the user
- Always clearly distinguish: extracted from paper vs inferred vs assumed
- Present the SDRF as a TSV code block for easy copy-paste
- Multiple `comment[modification parameters]` columns are normal (one per mod)
- Multiple `comment[sdrf template]` columns are normal (one per template)
