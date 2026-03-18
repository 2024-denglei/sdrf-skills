---
name: sdrf:improve
description: Use when the user wants to improve an existing SDRF file, make it more complete, more specific, or higher quality. Triggers on requests to improve, enhance, or review SDRF quality.
user-invocable: true
argument-hint: "[file path or paste SDRF content]"
---

# SDRF Improvement Workflow

You are analyzing an SDRF file to suggest improvements beyond basic validation.

## Step 1: Understand the Experiment

1. Read the SDRF content
2. Identify: organism, disease/condition, tissue, technology, label type
3. Detect which templates should apply (see sdrf-templates skill)
4. If a PXD accession is available → fetch PRIDE project context + publication for richer analysis

## Step 2: Assess Quality Dimensions

Evaluate the file on these 5 dimensions (score each 0-100):

### A. Completeness (are all useful columns present?)
- Read `spec/sdrf-proteomics/TERMS.tsv` and filter by detected template names in the `usage` column
- Are all REQUIRED columns for the detected templates present?
- Which RECOMMENDED columns are missing? (check individual template YAMLs for requirement levels)
- Which OPTIONAL columns would add value for this experiment type?
- Search for similar experiments in PRIDE to see what columns peers include:
  ```
  mcp PRIDE → search_extensive(query="<organism> <disease> <technology>")
  ```

### B. Specificity (are ontology terms precise enough?)
For each ontology-controlled column:
- Is the term specific enough for the experiment context?
- Could a more precise child term be used?
  ```
  mcp OLS → getChildren(ontologyId="<ont>", classIri="<iri>")
  ```
- Examples of insufficient specificity:
  - "cancer" → should be "breast invasive carcinoma"
  - "brain" → could be "temporal cortex" if the paper specifies
  - "blood" → could be "plasma" or "serum" if known

### C. Consistency (are values uniform across the file?)
- Case consistency: "Male" vs "male" vs "MALE"
- Format consistency: "58Y" vs "58 years" vs "58"
- Naming consistency: same sample described differently in different rows
- Ontology consistency: mixing EFO and MONDO for the same column

### D. Standards Compliance
- Read `spec/sdrf-proteomics/sdrf-templates/templates.yaml` for latest template versions
- Using latest template version?
- SDRF metadata columns present? (`comment[sdrf version]`, `comment[sdrf template]`)
- Modification format correct? (NT=;AC=;TA=;MT=)
- Reserved words used correctly? ("not available" not "N/A")
- Age format correct? ("58Y" not "58 years")

### E. Experimental Design Clarity
- Are factor values defined?
- Do factor values match a characteristics column?
- Is the experimental comparison clear from the SDRF alone?
- Are biological replicates numbered correctly?
- Are technical replicates identified?

## Step 3: Search for Improvement Context

Use MCP tools to gather improvement suggestions:

1. **Similar datasets**: Search PRIDE for well-annotated similar experiments
   ```
   mcp PRIDE → fetch_projects(keyword="<organism> <tissue> <technology>")
   ```

2. **Better ontology terms**: For each term, check if a more specific child exists
   ```
   mcp OLS → getChildren(ontologyId="<ont>", classIri="<current_term_iri>")
   ```

3. **Missing columns**: Check what columns similar experiments include
   - If human study without `characteristics[age]` → recommend adding
   - If TMT without proper channel labeling → recommend fixing
   - If DIA without `dia-acquisition` template columns → recommend

4. **Literature context** (if PXD available):
   - Does the paper mention metadata not captured in the SDRF?
   - Are there demographic details (age, sex) in the paper but not the SDRF?

## Step 4: Generate Improvement Report

Present improvements organized by priority:

### HIGH Priority (should fix)
Issues that affect data reuse or analysis pipeline compatibility.
- Missing required columns
- Wrong ontology accessions
- Missing factor values
- Incorrect modification format

### MEDIUM Priority (recommended)
Issues that affect metadata quality and findability.
- Terms that could be more specific
- Missing recommended columns (age, sex for human studies)
- Inconsistent formatting
- Missing SDRF metadata columns

### LOW Priority (nice to have)
Issues that improve completeness but aren't critical.
- Missing optional columns that similar experiments include
- Adding developmental stage, ancestry for human studies
- More detailed sample descriptions

### Quality Score

Calculate the overall score as a weighted average of the 5 dimensions:

```
Overall = (Completeness × 0.30) + (Specificity × 0.25) + (Consistency × 0.15)
        + (Standards × 0.15) + (Design × 0.15)
```

Scoring guide per dimension:
- **90-100**: Excellent — meets or exceeds community best practices
- **70-89**: Good — functional but has room for improvement
- **50-69**: Needs work — missing important metadata or has significant issues
- **0-49**: Poor — major structural or semantic problems

Present the score:
```
Quality Score: 72/100

  Completeness:  85/100 ████████░░ — Missing: cell type, developmental stage
  Specificity:   60/100 ██████░░░░ — "cancer" should be more specific
  Consistency:   90/100 █████████░ — Minor case mismatch in 2 rows
  Standards:     55/100 █████░░░░░ — Not using latest template, missing metadata columns
  Design:        70/100 ███████░░░ — Factor values defined but replication unclear

  Weighted: (85×0.30)+(60×0.25)+(90×0.15)+(55×0.15)+(70×0.15) = 72.25 → 72/100
```

## Step 5: Offer to Fix

For each improvement, offer to make the change:
- Show the current value → proposed value
- Explain WHY the change improves the SDRF
- Let the user approve/reject each change
- Generate the corrected SDRF as a TSV code block
