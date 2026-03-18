# sdrf-skills for Codex

## Installation

First, ensure submodules are initialized (the spec data is required):

```bash
git submodule update --init --recursive
```

Symlink the skills and spec directories into your Codex agents skills path:

```bash
ln -s "$(pwd)/skills" ~/.agents/skills/sdrf-skills
ln -s "$(pwd)/spec" ~/.agents/skills/sdrf-skills/spec
```

Or copy both directories:

```bash
cp -r skills/ ~/.agents/skills/sdrf-skills/
cp -r spec/ ~/.agents/skills/sdrf-skills/spec/
```

## What it provides

12 structured workflows (SKILL.md files) that encode expert-level SDRF annotation methodology:

| Skill | Purpose |
|-------|---------|
| sdrf-knowledge | SDRF format rules, column names, ontology mappings |
| sdrf-templates | Template system, layer selection, mutual exclusivity |
| sdrf-annotate | Full annotation: PXD → PRIDE + paper → draft SDRF |
| sdrf-validate | Validation against templates + OLS checking |
| sdrf-improve | Quality scoring: specificity, completeness, consistency |
| sdrf-fix | Auto-fix UNIMOD swaps, case, format, artifacts |
| sdrf-terms | Ontology term lookup for any SDRF column |
| sdrf-brainstorm | Pre-annotation metadata planning |
| sdrf-review | Quality review with paper + PRIDE cross-reference |
| sdrf-explain | Plain-language SDRF education |
| sdrf-convert | Pipeline selection (MaxQuant, DIA-NN, quantms) |
| sdrf-design | Experimental design analysis |

## Usage

Each SKILL.md file contains a complete workflow. Reference them from your Codex instructions:

```
When annotating SDRF files, follow the workflow in skills/sdrf-annotate/SKILL.md
```

## Prerequisites

These skills reference external APIs (OLS, PRIDE, PubMed) for ontology validation
and metadata retrieval. Configure appropriate API access in your Codex environment.
