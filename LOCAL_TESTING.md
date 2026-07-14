# Local testing in KNIME 5.12 (Windows)

Step-by-step to load and smoke-test the Euleris + GraphCoherence Python nodes
in KNIME 5.12.0 LTS before publishing to the Community Hub.

> **Read first — two things that will block you:**
>
> 1. **One extension, one manifest.** KNIME's pure-Python loader requires **one
>    extension per `knime.yml` with a single `extension_module`**. This repo ships
>    that manifest at **`src/knime.yml`** plus the aggregator module
>    `src/cognitive_engineering_knime.py`, which imports both node packages so a
>    single extension registers all three nodes.
> 2. **The nodes call the live API.** `configure()` (schema/dialog) works offline,
>    but `execute()` calls `https://api.cognitive-engineering.dev`. Until that
>    endpoint is deployed **and** you have a real `ek_`/`gc_` key, execution will
>    fail with a connection error. You can still verify the extension **loads,
>    the nodes appear, and dialogs configure correctly** — see the offline note
>    in step 3.

---

## 0. Prerequisites

- **KNIME 5.12.0 LTS** installed (you have this).
- **Conda** (Miniforge recommended). `knime-python-base` / `knime-extension` are
  only on the `knime` conda channel — they are **not** pip-installable, so a
  plain venv will not work. If you don't have conda:
  - Download Miniforge: https://github.com/conda-forge/miniforge (Windows x86-64),
    install to e.g. `C:\Users\41763\miniforge3`.
  - Your system Python 3.13 at `C:\Users\41763\AppData\Local\Programs\Python\Python313\`
    is **not** used here — the conda env brings its own Python 3.11.

Open **"Miniforge Prompt"** (Start menu) for all conda commands below.

---

## 1. Create the Python environment

From this repo's root:

```bat
conda env create -f dev\env.yml
conda activate cognitive-engineering-knime
```

Verify the three runtime packages import:

```bat
python -c "import knime.extension, pandas, euleris, graphcoherence; print('env OK')"
```

Get the env's absolute path (you need it in step 2):

```bat
conda env list
```

Copy the path shown for `cognitive-engineering-knime`
(e.g. `C:\Users\41763\miniforge3\envs\cognitive-engineering-knime`).

> If `conda env create` fails resolving `knime-python-base=5.12` /
> `knime-extension=5.12`, edit `dev\env.yml`, remove the `=5.12` pins, recreate,
> then run `conda list knime-extension` and re-pin to the version shown.

---

## 2. Point KNIME at the extension

### 2a. Create your `config.yml`

```bat
copy dev\config.yml.example dev\config.yml
```

Open `dev\config.yml` and set the two paths
(**forward slashes on Windows**):

```yaml
dev.cognitive_engineering.cognitive_engineering:
  src: C:/dev/knime-cognitive-engineering/src
  conda_env_path: C:/Users/41763/miniforge3/envs/cognitive-engineering-knime
  debug_mode: true
```

- The top key **must** equal the extension id = `group_id.name` from
  `src/knime.yml` → `dev.cognitive_engineering.cognitive_engineering`.
- `src` points at the folder containing `src/knime.yml` (i.e. `.../knime-nodes/src`).
- `conda_env_path` is the path from `conda env list`.

### 2b. Edit `knime.ini`

`knime.ini` is in your KNIME install folder, typically:
`C:\Program Files\KNIME\knime.ini` (edit as Administrator), or for a user
install `C:\Users\41763\...\KNIME\knime.ini`.

Add this as a **new line at the very end** (each JVM arg on its own line, and it
**must** come after the `-vmargs` line already in the file):

```
-Dknime.python.extension.config=C:/dev/knime-cognitive-engineering/dev/config.yml
```

Use forward slashes here too, on Windows.

### 2c. Restart KNIME

Fully close and reopen KNIME. On start it reads `config.yml`, loads the env, and
registers the nodes.

---

## 3. Confirm the extension registered

- In the **Node Repository** panel (bottom-left; if hidden: *View → Node
  Repository*), the three nodes appear under **Uncategorized** — dev-loaded
  Python extensions can't create categories in KNIME 5.x (they get their proper
  categories only once published). Search "Euleris" / "GraphCoherence":
  - *Euleris Spectrum*, *Euleris Batch*
  - *GraphCoherence Analyzer*
- Or use the repository search box: type `Euleris` and `GraphCoherence`.

**Offline check (no API needed):** drag a node onto the canvas and double-click
it. The configuration dialog should open with the **SMILES column / Source /
Target** dropdowns and the **API Key** field. If the dialog opens and columns
populate from an upstream table, `configure()` works — that alone proves the
extension loaded correctly, even before the API is deployed.

`debug_mode: true` means you can edit `src/**/_logic.py` or `nodes.py` and just
re-execute the node — no KNIME restart needed (a restart is only needed for
`knime.yml`/new-node changes).

---

## 4. Smoke-test workflow (build manually)

> Full **execution** needs the deployed API + a real key. If the API isn't live
> yet, do the offline check in step 3 instead; the steps below are the
> end-to-end test for once it is deployed.

Create a new workflow: *File → New… → New KNIME Workflow*.

### Branch A — Euleris

1. Drag **Table Creator** (Node Repository → *IO → Other*) onto the canvas.
   Double-click → add one **string** column named `smiles` with three rows:
   ```
   CCO
   c1ccccc1
   c1cn[nH]n1
   ```
2. Drag **Euleris Spectrum** next to it. Connect Table Creator's output port to
   the Euleris Spectrum input port (drag between the black triangles).
3. Double-click **Euleris Spectrum**:
   - **SMILES column**: `smiles`
   - **API Key**: your `ek_…` key (from https://cognitive-engineering.dev).
4. Right-click the node → **Execute**. Right-click → **Open output table** (or
   the last port view).

**Expected output** (input row + appended `euleris_*` columns):

| smiles | euleris_score | euleris_N3..N10 | euleris_cycles | tox / adme |
|---|---|---|---|---|
| `CCO` (ethanol, acyclic) | low | **all N = 0** | 0 | populated floats |
| `c1ccccc1` (benzene) | higher | **N6 = 1**, rest 0 | 1 | populated |
| `c1cn[nH]n1` (1,2,4-triazole) | ~35 | **N5 = 1**, rest 0 | 1 | populated |

An invalid SMILES would **not** crash the node — its `euleris_*` cells come back
missing (red "?") and a warning appears in the KNIME console.

### Branch B — GraphCoherence

1. Drag a second **Table Creator**. Add two **int** columns `source`, `target`
   with rows:
   ```
   source, target
   0, 1
   1, 2
   2, 0
   2, 3
   ```
2. Drag **GraphCoherence Analyzer**; connect the Table Creator to its input.
3. Double-click:
   - **Source Column**: `source`; **Target Column**: `target`
   - **API Key**: your `gc_…` key
   - **C parameter**: `0.0`
4. Execute. It has **two output ports**:

**Port 1 — Edge table** (one row per edge):

| source | target | edge_key | gc_tri_count | gc_state | gc_ricci | gc_ccrit |
|---|---|---|---|---|---|---|
| 0 | 1 | 0--1 | 1 | pre | … | 0.8 |
| 1 | 2 | 1--2 | 1 | pre | … | 0.8 |
| 2 | 0 | 0--2 | 1 | pre | … | 0.8 |
| 2 | 3 | 2--3 | 0 | **always_fragile** | … | *(missing — ∞)* |

(The 0-1-2 triangle gives those three edges `tri=1`; edge 2-3 is a bridge with
`tri=0`. At `C=0.0` the triangle edges are below their `ccrit=0.8`, so `pre`.)

**Port 2 — Network summary** (single row):

| gc_fi | gc_nodes | gc_edges | gc_triangles | gc_mean_ricci | gc_regime |
|---|---|---|---|---|---|
| **0.25** (1 of 4 edges is tri=0) | 4 | 4 | 3 | … | … |

---

## 5. Troubleshooting

**Nodes don't appear in the repository**
- Re-check `knime.ini`: the `-Dknime.python.extension.config=…` line is present,
  uses **forward slashes**, and is **below** `-vmargs`. One arg per line.
- The `config.yml` top key must exactly match `dev.cognitive_engineering.cognitive_engineering`.
- `src` must point at the folder that contains `knime.yml`
  (`…/knime-nodes/src`), not the repo root.
- Look at the KNIME **log**: *View → Open KNIME log*, or
  `C:\Users\41763\knime-workspace\.metadata\knime\knime.log`. Search for
  `cognitive_engineering`, `extension`, `ModuleNotFoundError`, `Traceback`.

**"ModuleNotFoundError: knime" / import errors on load**
- `conda_env_path` in `config.yml` is wrong. Confirm with `conda env list` and
  that `python -c "import knime.extension"` works **inside that env**.

**"ModuleNotFoundError: euleris" (or graphcoherence/pandas) at execute time**
- Those live in the conda env's pip section. Re-run:
  `conda activate cognitive-engineering-knime && pip install euleris graphcoherence pandas`.

**Icons look tiny / blank** — expected: they are 16×16. KNIME's guide recommends
48×48; regenerate larger before publishing if desired.

**Execute fails with a connection/timeout error** — the API endpoint
(`api.cognitive-engineering.dev`) is not deployed yet, or the node has no valid
key. This is expected pre-deploy; the load/configure check in step 3 is the
offline-valid test.

**HTTP 429 in the node** — daily quota hit; the node surfaces a clear error with
the upgrade link (`https://cognitive-engineering.dev/pricing`).

**Check the Python console for errors** — right-click a failing node →
*Configure* has no console, but execution errors show in the node's yellow/red
status tooltip and in the KNIME log (above). For deeper Python debugging set
`debug_mode: true` (already set) and watch the log while executing.

---

## 6. Before publishing to the Community Hub

- Switch from the dev `config.yml`/`conda_env_path` flow to a **bundled** env
  (`env_type: bundled`, conda-pack) per the bundling guide:
  https://docs.knime.com/latest/pure_python_node_extensions_guide/#_bundling
- Add real screenshots to `README.md`.
