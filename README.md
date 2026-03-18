# sdrf-skills — SDRF Annotation Skills

Structured skills that give AI assistants expert-level capabilities for annotating,
validating, improving, and brainstorming proteomics metadata in the
[SDRF](https://github.com/bigbio/proteomics-metadata-standard) format.

Inspired by [superpowers](https://github.com/obra/superpowers) — structured skills
that encode community expertise as repeatable workflows, not ad-hoc guesses.

## What it does

Instead of an AI guessing at ontology terms or SDRF rules, these skills teach it
**exactly how** to annotate proteomics datasets — using real tools (OLS, PRIDE, PubMed)
guided by the methodology of experienced annotators.

The SDRF specification data (column definitions, templates) lives in a git submodule
and is read at runtime — so the skills stay current when the spec evolves.

All 12 skills are under the `sdrf:` namespace. In Claude Code, type `/sdrf:` and autocomplete will show them all.

| Skill | What it does |
|-------|-------------|
| `/sdrf:knowledge` | Ask about SDRF format, column rules, ontology mappings, reserved words |
| `/sdrf:templates` | Ask about templates, select templates, understand layers and selection rules |
| `/sdrf:annotate` | Full annotation workflow: PXD → PRIDE + paper → draft SDRF → validate |
| `/sdrf:validate` | Systematic validation against templates + ontology checking via OLS |
| `/sdrf:improve` | Quality analysis: specificity, completeness, consistency, score |
| `/sdrf:fix` | Auto-fix common errors (UNIMOD swaps, case, format, artifacts) |
| `/sdrf:terms` | Find and verify ontology terms for any SDRF column |
| `/sdrf:brainstorm` | Plan metadata strategy before creating an SDRF |
| `/sdrf:review` | Comprehensive quality review with cross-reference to paper + PRIDE |
| `/sdrf:explain` | Explain any column, error, or concept in plain language |
| `/sdrf:convert` | Choose and configure analysis pipelines from SDRF |
| `/sdrf:design` | Detect batch effects, confounders, replication issues |

## Installation

### Clone with submodules (required)

The SDRF specification data is included as a git submodule. You must initialize it:

```bash
# Clone with submodules:
git clone --recurse-submodules https://github.com/bigbio/sdrf-skills

# Or if already cloned without submodules:
cd sdrf-skills
git submodule update --init --recursive
```

To update the spec to the latest version:
```bash
git submodule update --remote --recursive
```

### Claude Code (Plugin)
```bash
# From the official marketplace (when published):
/plugin install sdrf-skills

# Or from GitHub:
/plugin install github:bigbio/sdrf-skills
```

### Manual Installation (Claude Code)
Copy the `skills/` and `spec/` directories to your Claude Code skills path:
```bash
cp -r skills/* ~/.claude/skills/
cp -r spec/ ~/.claude/skills/spec/
```

### Cursor
The `.cursor/rules/sdrf-skills.mdc` file is included. It activates automatically when
working with `*.sdrf.tsv` files and references the skill workflows.

```bash
# Clone into your project or copy the rules file:
cp .cursor/rules/sdrf-skills.mdc /your-project/.cursor/rules/
cp -r skills/ /your-project/skills/
cp -r spec/ /your-project/spec/
```

### Codex (OpenAI)
See `.codex/INSTALL.md`. Symlink the skills into your agents path:
```bash
ln -s "$(pwd)/skills" ~/.agents/skills/sdrf-skills
ln -s "$(pwd)/spec" ~/.agents/skills/sdrf-skills/spec
```

### Gemini CLI
The `GEMINI.md` file at the project root is automatically picked up by Gemini CLI.
It references the skill workflows in the `skills/` directory.

### OpenCode
See `.opencode/AGENTS.md`. It provides the skill reference for OpenCode agents.

## Prerequisites

This plugin expects the following MCP servers to be configured in your Claude setup:

- **OLS** — Ontology Lookup Service (EBI)
- **PRIDE MCP** — Proteomics dataset repository
- **PubMed** — Biomedical literature
- **bioRxiv** — Preprint server
- **Consensus** — Academic research search
- **Open Targets** — Disease-target associations

These provide the real-time data access. The skills provide the methodology.

## Example Usage

### Ask about templates
```
You: /sdrf:templates I have a DIA phosphoproteomics study on mouse brain

Claude: For your experiment, I recommend:
  1. ms-proteomics (mass spectrometry)
  2. vertebrates (Mus musculus)
  3. dia-acquisition (DIA method)

  This adds columns for: strain, developmental stage, DIA scan windows...
```

### Annotate a PRIDE dataset
```
You: /sdrf:annotate PXD045678

Claude:
  → Fetches PRIDE metadata (organism, instrument, files)
  → Finds the paper (PMID from PRIDE → PubMed → full text from PMC)
  → Extracts sample info from methods section
  → Selects templates: ms-proteomics + human + clinical-metadata
  → Drafts SDRF with verified ontology terms from OLS
  → Validates the result
```

### Ask about SDRF rules
```
You: /sdrf:knowledge What format should modification parameters use?

Claude: The format for comment[modification parameters] is:
  NT=<name>;AC=UNIMOD:<id>;TA=<amino acid>;MT=<Fixed|Variable>

  Example: NT=Carbamidomethyl;AC=UNIMOD:4;TA=C;MT=Fixed
  Warning: UNIMOD:1 = Acetyl, UNIMOD:21 = Phospho (most common swap!)
```

### Fix an SDRF with errors
```
You: /sdrf:fix [paste SDRF content]

Claude:
  → Identifies: UNIMOD:21 used for Acetyl (should be UNIMOD:1)
  → Fixes case: "Male" → "male"
  → Fixes format: "58 years" → "58Y"
  → Fixes artifacts: "['breast cancer']" → "breast cancer"
  → Shows changelog → outputs corrected SDRF
```

### Find the right ontology term
```
You: /sdrf:terms disease "liver cancer"

Claude:
  → Searches EFO, MONDO, DOID via OLS
  → Recommends: hepatocellular carcinoma (EFO:0000182)
  → Shows alternatives: liver carcinoma, cholangiocarcinoma
  → Checks specificity: "liver cancer" too generic → use subtype
```

## Architecture

```
sdrf-skills/
├── .claude-plugin/plugin.json    # Claude Code — plugin manifest
├── .cursor/rules/sdrf-skills.mdc # Cursor — rules file (auto-activates on *.sdrf.tsv)
├── .codex/INSTALL.md             # Codex — installation instructions
├── .opencode/AGENTS.md           # OpenCode — agent reference
├── hooks/hooks.json              # Claude Code — session initialization
├── spec/                         # ← Git submodule: proteomics-metadata-standard
│   └── sdrf-proteomics/
│       ├── TERMS.tsv             # Column definitions (read by skills at runtime)
│       └── sdrf-templates/       # ← Nested submodule: sdrf-templates
│           ├── templates.yaml    # Template manifest (read by skills at runtime)
│           └── {name}/{ver}/     # Individual template YAMLs
├── skills/                       # ← Portable across ALL platforms
│   ├── sdrf-knowledge/SKILL.md   # /sdrf:knowledge — SDRF spec, columns, ontologies
│   ├── sdrf-templates/SKILL.md   # /sdrf:templates — template system, layers, selection
│   ├── sdrf-annotate/SKILL.md    # /sdrf:annotate — full annotation workflow
│   ├── sdrf-validate/SKILL.md    # /sdrf:validate — validation + OLS checking
│   ├── sdrf-improve/SKILL.md     # /sdrf:improve — quality analysis + scoring
│   ├── sdrf-fix/SKILL.md         # /sdrf:fix — auto-fix common errors
│   ├── sdrf-terms/SKILL.md       # /sdrf:terms — ontology term lookup
│   ├── sdrf-brainstorm/SKILL.md  # /sdrf:brainstorm — metadata planning
│   ├── sdrf-review/SKILL.md      # /sdrf:review — comprehensive review
│   ├── sdrf-explain/SKILL.md     # /sdrf:explain — explain any concept
│   ├── sdrf-convert/SKILL.md     # /sdrf:convert — pipeline guidance
│   └── sdrf-design/SKILL.md      # /sdrf:design — experimental design analysis
├── CLAUDE.md                     # Claude Code — project config
├── GEMINI.md                     # Gemini CLI — project config
├── BRAINSTORM.md                 # Design document
└── README.md                     # This file
```

## Cross-Platform Design

The core of this plugin is the `skills/` directory — 12 markdown files that encode
annotation methodology. These are **platform-agnostic**. Each platform just needs a
thin shim to discover and load them:

| Platform | Config File | How It Works |
|----------|------------|--------------|
| Claude Code | `.claude-plugin/plugin.json` + `CLAUDE.md` | Native plugin — skills auto-discovered, `/sdrf:*` commands |
| Cursor | `.cursor/rules/sdrf-skills.mdc` | Rules file with glob trigger on `*.sdrf.tsv` |
| Codex | `.codex/INSTALL.md` | Symlink skills to `~/.agents/skills/` |
| Gemini CLI | `GEMINI.md` | Project-level instructions, auto-loaded |
| OpenCode | `.opencode/AGENTS.md` | Agent reference file |

The skills themselves work on any AI assistant that can read markdown and call
external APIs (OLS, PRIDE, PubMed). The specification data in `spec/` stays
current via the git submodule — no skills need updating when the spec changes.

## Why Skills Instead of an MCP Server?

The tools AI assistants need already exist as MCP servers (OLS, PRIDE, PubMed).
What was missing was **the expertise** — knowing:

- Which ontology to search for which column
- How to read a paper and extract SDRF metadata
- What the most common annotation errors are and how to fix them
- How to select the right templates for an experiment
- What "good" SDRF annotation looks like

Skills encode this expertise as structured workflows that any AI assistant follows step by step.
No custom code to build, deploy, or maintain — just markdown files that teach the AI
the methodology of an experienced SDRF annotator.

## Updating the Specification

The SDRF specification evolves independently. To pull the latest:

```bash
# Update to latest spec:
git submodule update --remote --recursive

# Commit the updated reference:
git add spec
git commit -m "Update SDRF spec to latest version"
```

Skills read `spec/` files at runtime, so updating the submodule is all that's needed.
No SKILL.md files need to be modified when columns or templates change.

## Contributing

To add a new skill:
1. Create `skills/your-skill/SKILL.md` with YAML frontmatter
2. Write the workflow instructions in markdown
3. Reference `spec/` files for any specification data (never hardcode)
4. Test with Claude Code: `/your-skill [arguments]`

## License

MIT
