# Publishing to the KNIME Community Hub

How to distribute the Cognitive Engineering nodes (Euleris + GraphCoherence)
beyond local dev. Two paths — start with A, aim for B.

> Distribution model, in one line: KNIME **Python extensions are installed from an
> "update site"** (a generated repository folder/zip), *not* uploaded like a
> workflow. So both options below first **bundle** the extension into an update
> site, then differ in how that site is shared.

---

## Prerequisite for bundling (one-time repo change)

The dev loader uses `dev/env.yml` (conda) + `dev/config.yml`. **Bundling needs an
environment spec referenced from `knime.yml`.** Current KNIME uses a `pixi.toml`;
add its path to `src/knime.yml`:

```yaml
pixi_toml_path: ./pixi.toml
```

and add a `pixi.toml` next to `src/knime.yml` with a build feature:

```toml
[workspace]
channels = ["knime", "conda-forge"]
name = "cognitive-engineering-knime"
platforms = ["win-64", "linux-64", "osx-64", "osx-arm64"]
version = "0.1.0"

[dependencies]
python = "3.11.*"
knime-extension = "{version_ap}"
knime-python-base = "{version_ap}"
pandas = "*"

# euleris / graphcoherence are PyPI-only — add via pixi's pypi-dependencies:
[pypi-dependencies]
euleris = ">=0.1.0"
graphcoherence = ">=0.1.0"

[feature.build.dependencies]
python = "3.11.*"
knime-extension-bundling = "{version_ap}"

[environments]
build = { features = ["build"], no-default-feature = true }
```

(If you prefer the older conda flow, use `env_yml_path: ./env.yml` instead of
`pixi_toml_path` and run the bundler against a conda env — see the bundling guide.)

---

## Build the update site (both options need this)

From the folder containing `knime.yml` (`src`):

```bash
# pixi task (recommended)
pixi run build dest=../dist

# …or invoke the bundler directly, pinning the KNIME version:
python build_python_extension.py . ../dist --knime-version 5.12
```

This creates the `build` environment, conda-packs it, and writes an **update-site
repository** to `../dist`. Reference: the bundling guide
https://docs.knime.com/latest/pure_python_node_extensions_guide/#_bundling

---

## Option A — Self-distributed update site (fastest, no KNIME review)

Best for v0.1 and internal/early users.

1. Build the update site (above) → `dist/`.
2. Zip it (or host the folder somewhere users can reach).
3. Users install it in KNIME:
   - **File → Preferences → Install/Update → Available Software Sites → Add…**
     and point at the folder/zip (local path or URL).
   - **File → Install KNIME Extensions…**, find *Cognitive Engineering* nodes,
     Install, restart.
4. (Optional) Create a KNIME Hub account at https://hub.knime.com
   (suggested user: `cognitive-engineering` or `dmartinv`) to host the zip and a
   demo **workflow** showcasing the nodes — workflows *are* uploaded directly to
   the Hub and are a good discovery surface pointing back to the extension.

**Pros:** ship today, full control. **Cons:** users must manually add the site;
not discoverable in KNIME's built-in extension list.

---

## Option B — KNIME Community Extensions program (wide distribution, the goal)

Gets the extension into KNIME's **Community Extensions update site** so anyone can
install it from KNIME's built-in dialog without adding a custom site.

1. Host the built update site publicly (GitHub Pages, S3, or your VPS).
2. Apply to the KNIME **Community Extensions / Community Partner** program and
   submit the extension for review (they publish trusted extensions to the
   community update site; there is also an *experimental* tier for earlier listing).
   Start from the community contribution docs on https://www.knime.com/community
   and the examples/structure in https://github.com/knime/knime-python-types.
3. Once accepted, users enable the KNIME Community Extensions site (bundled with
   KNIME) and install *Cognitive Engineering* directly via **File → Install KNIME
   Extensions**.

**Pros:** installable by everyone, discoverable, trusted badge. **Cons:** requires
KNIME review + a publicly hosted, maintained update site.

---

## Checklist before either option

- [ ] Reconcile `knime.yml` for bundling (`pixi_toml_path` + `pixi.toml`, above).
- [ ] `python -m pytest` green (pure-logic tests).
- [ ] Smoke-tested in KNIME per `LOCAL_TESTING.md` (nodes load, dialogs configure).
- [ ] End-to-end execute verified against the deployed API with real `ek_`/`gc_` keys.
- [ ] Icons 48×48 (done), README screenshots added.
- [ ] `version` bumped in `src/knime.yml` if re-releasing.
