---
name: sdrf:improve
description: Use when the user wants to improve an existing SDRF file strictly according to SDRF templates and specification rules (no speculative additions).
user-invocable: true
argument-hint: "[file path or paste SDRF content]"
---

# SDRF Specification-Driven Improvement Workflow

You are improving an SDRF file using ONLY specification/template rules.

Do not suggest additions based on:
- Similar datasets in PRIDE
- Literature expectations not encoded in templates
- "Could be more detailed" heuristics
- Personal curator preference

If a change is not justified by template metadata (`required`/`recommended`) or
TERMS.tsv rules, do not recommend it.

## Authoritative Sources (must read)

1. `spec/sdrf-proteomics/TERMS.tsv`
2. `spec/sdrf-proteomics/sdrf-templates/templates.yaml`
3. `spec/sdrf-proteomics/sdrf-templates/{name}/{version}/{name}.yaml` for each template in use

For affinity-proteomics, align with the official template/spec rules:
- Technology template: `affinity-proteomics`
- Optional experiment child template: `olink` OR `somascan` (mutually exclusive)

## Step 1: Determine Active Templates

1. Parse `comment[sdrf template]` columns (NT/VV format).
2. If missing/incomplete, detect from SDRF content and technology type.
3. Confirm template set with the user before proposing edits.

Do not "upgrade" template versions automatically. If a newer version exists, report it as an optional migration task.

## Step 2: Build Rule Matrix

Construct an explicit checklist from template YAML files:
- Required columns
- Recommended columns
- Optional columns
- Column validators (values/patterns/ontology)
- Allowed reserved words (`not available`, `not applicable`, `pooled`) via TERMS.tsv flags

For affinity-proteomics specifically, ensure checks include:
- `comment[platform]` (required)
- `comment[panel name]` (recommended)
- `comment[quantification unit]` (optional; values include NPX/RFU in spec)
- `comment[normalization method]` (optional)
- `comment[fraction identifier]` (optional)

And for child templates:
- Olink: check Olink-specific required/recommended columns from `olink.yaml`
- SomaScan: check SomaScan-specific required/recommended columns from `somascan.yaml`

## Step 3: Identify Spec-Backed Improvements

Classify findings into these categories only:

### A. Required Fixes (must change)
- Missing required columns from active templates
- Invalid column names not matching SDRF naming patterns
- Values violating template/TERMS validators
- Invalid reserved words per TERMS flags

### B. Recommended Fixes (should change)
- Missing columns marked `recommended` in active templates
- Values that fail recommended validators (warnings)

### C. Optional Enhancements (may change)
- Missing optional columns from active templates
- Only include if explicitly present in template metadata

Do not include free-form "quality" recommendations outside A/B/C.

## Step 4: Generate Deterministic Report

Report every finding with source traceability:
- Column or value issue
- Severity (`required` / `recommended` / `optional`)
- Exact source rule:
  - template file + column definition, or
  - TERMS.tsv field (usage/values/allow_not_available/allow_not_applicable/allow_pooled)
- Proposed correction

Example format:
```text
Finding: Missing column `comment[panel name]`
Severity: recommended
Source: spec/sdrf-proteomics/sdrf-templates/affinity-proteomics/1.0.0/affinity-proteomics.yaml
Action: Add `comment[panel name]` with panel identifier values.
```

## Step 5: Apply Changes Only with User Approval

Before modifying file contents:
1. Show the exact changes (old -> new)
2. Group by severity (required first)
3. Ask user approval for recommended/optional changes

Required fixes can be applied directly if the user asked to "fix all required issues."

## Output Constraints

- No speculative metadata additions
- No PRIDE peer comparison suggestions
- No literature-derived additions unless already required/recommended by templates
- No ontology "more specific child" suggestions unless validator explicitly requires a value constraint

The goal is strict conformance improvement, not curation enrichment.
