# Cognitive Engineering — KNIME Nodes

Pure-Python KNIME 5.x node extensions that bring **Euleris** (topological
molecular analysis) and **GraphCoherence** (structural network analysis) into
KNIME workflows. The nodes are thin clients over the live PyPI packages
[`euleris`](https://pypi.org/project/euleris/) and
[`graphcoherence`](https://pypi.org/project/graphcoherence/): all computation
happens **server-side** via the Cognitive Engineering API. The nodes only send
your table data and append the returned columns.

This repository contains **only the KNIME node code** — HTTP client wrappers over
the public API. There is no proprietary or server-side code here.

## Nodes

### Euleris

- **Euleris Spectrum** — for each molecule in a SMILES column, appends the cycle
  spectrum `euleris_N3`…`euleris_N10`, the topological complexity `euleris_score`,
  the total cycle count `euleris_cycles`, ADME predictions `euleris_logP`,
  `euleris_esol`, `euleris_bbbp`, and toxicity `euleris_tox_score`,
  `euleris_tox_risk`, `euleris_tox_AhR`, `euleris_tox_ER_LBD`, `euleris_tox_MMP`.
  Invalid SMILES do not stop the run — the offending row's new columns are left
  empty (missing) and a warning is logged.
- **Euleris Batch** — high-throughput variant that sends molecules to the batch
  endpoint in configurable chunks (**Batch Size**, 1–1000) and appends the
  spectrum, `euleris_score`, and toxicity summary columns. Results are aligned
  back to the input rows by SMILES; molecules the API rejects are left empty.

### GraphCoherence

- **GraphCoherence Analyzer** — takes an edge list (a **Source** and a
  **Target** column, integer or string) and produces **two** output tables:
  - *Edge table*: one row per edge — `source`, `target`, `edge_key`,
    `gc_tri_count` (local triangle motif count), `gc_state`
    (`solid` / `pre` / `always_fragile`), `gc_ricci` (Ollivier-Ricci
    curvature, if available), `gc_ccrit` (critical coupling; empty for
    always-fragile edges).
  - *Network summary*: a single row — `gc_fi` (fragility index = fraction of
    edges with no triangle), `gc_nodes`, `gc_edges`, `gc_triangles`,
    `gc_mean_ricci`, `gc_regime`, `gc_regime_tau`.
  - **C parameter** sets the coupling threshold used for edge classification.

## Prerequisites

- **KNIME Analytics Platform 5.12+**
- An **API key** from <https://cognitive-engineering.dev> (Euleris keys start
  with `ek_`, GraphCoherence keys with `gc_`). No keys are stored in this
  extension — you paste them into each node's dialog at run time.
- The nodes depend on the PyPI packages
  [`euleris`](https://pypi.org/project/euleris/) and
  [`graphcoherence`](https://pypi.org/project/graphcoherence/), plus `pandas`.

## Installation (for users)

Install from the Cognitive Engineering update site:

1. **File → Preferences → Install/Update → Available Software Sites → Add…**
   and enter the update site URL:
   ```
   https://knime.cognitive-engineering.dev
   ```
2. **File → Install KNIME Extensions…**, find the *Cognitive Engineering* nodes
   (Euleris Spectrum, Euleris Batch, GraphCoherence Analyzer), install, and
   restart KNIME.

Then, in each node's dialog, paste your API key into **API Key**, select the
relevant column(s), and run. If you hit your daily quota the node fails with a
`429` message that includes the upgrade link
<https://cognitive-engineering.dev/pricing>.

> **Getting API keys**
> - Euleris: <https://cognitive-engineering.dev/euleris/app/settings>
> - GraphCoherence: <https://cognitive-engineering.dev/graphcoherence/settings>

## Development setup

For loading the nodes locally from source (before/instead of installing from the
update site). Full walkthrough — env, smoke-test workflow, troubleshooting — is
in [`LOCAL_TESTING.md`](LOCAL_TESTING.md). Quick version:

### Prerequisites
- KNIME Analytics Platform 5.12+
- Miniforge or Anaconda. `knime-extension` / `knime-python-base` are conda-only
  (not on PyPI), so a plain venv will not work.

### Steps
1. Install the conda environment:
   ```
   conda env create -f dev/env.yml
   ```
2. Copy and edit the config file (use forward slashes, even on Windows):
   ```
   cp dev/config.yml.example dev/config.yml
   # edit `src` and `conda_env_path` in dev/config.yml
   ```
   `src` must point at this repo's `src/` directory (the folder containing
   `knime.yml`); `conda_env_path` is the env path from `conda env list`.
3. Add to your KNIME `knime.ini` (a new line, after `-vmargs`):
   ```
   -Dknime.python.extension.config=/absolute/path/to/dev/config.yml
   ```
4. Restart KNIME. In dev mode the three nodes appear under **Uncategorized** in
   the Node Repository — search "Euleris" / "GraphCoherence".

> **Note on node categories.** In local development mode, nodes appear under
> "Uncategorized" — a KNIME 5.x limitation: dev-loaded Python extensions cannot
> create categories dynamically. When published through the KNIME Community
> Extensions program, nodes appear under their designated categories.

## Running the tests

```bash
python -m pip install pandas Pillow pytest
python -m pytest -q
```

The tests exercise only the pure `_logic` modules and never require a KNIME
runtime or the live API (fake result objects stand in for the API responses).

## Architecture

- `src/*/_logic.py` — pure pandas transforms, **no** `import knime`; fully
  unit-tested.
- `src/*/nodes.py` — thin `knime.extension` node classes that wire config →
  pure logic (injecting `euleris.analyze` / `euleris.batch` / `gc.preview`) →
  `knext.Table`.
- `src/cognitive_engineering_knime.py` — aggregator module that imports both node
  packages so a single extension registers all three nodes.

## Publishing to the KNIME Community Hub

To bundle the extension into an installable update site and distribute it, see
[`PUBLISH.md`](PUBLISH.md).

## Related packages

- [`euleris`](https://pypi.org/project/euleris/) — Python client for the Euleris
  topological molecular analysis API.
- [`graphcoherence`](https://pypi.org/project/graphcoherence/) — Python client for
  the GraphCoherence structural network analysis API.

## License

[Apache License 2.0](LICENSE).
