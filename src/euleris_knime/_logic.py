"""Pure data logic for the Euleris KNIME nodes.

This module contains NO ``import knime`` - every function here is a plain
pandas transformation so it can be unit-tested without a KNIME runtime.
The node classes in ``nodes.py`` inject the live API callables
(``euleris.analyze`` / ``euleris.batch``) and progress/warn callbacks.
"""

from __future__ import annotations

import pandas as pd

# Spectrum keys, canonical order (matches euleris MoleculeResult.spectrum).
_SPECTRUM_KEYS = ["N3", "N4", "N5", "N6", "N7", "N8", "N9", "N10"]

# ADME prediction keys we surface (predictions[...].value).
_ADME_KEYS = {"logp": "euleris_logP", "esol": "euleris_esol", "bbbp": "euleris_bbbp"}

# Toxicity endpoint keys we surface (toxicity.endpoints[...].probability).
_TOX_ENDPOINTS = {
    "NR_AhR": "euleris_tox_AhR",
    "NR_ER_LBD": "euleris_tox_ER_LBD",
    "SR_MMP": "euleris_tox_MMP",
}

# Ordered (name, dtype) list. Both configure() (schema) and the tests
# reference this to guarantee the exact output columns / order.
EULERIS_OUTPUT_COLUMNS = [
    ("euleris_score", "int"),
    ("euleris_N3", "int"),
    ("euleris_N4", "int"),
    ("euleris_N5", "int"),
    ("euleris_N6", "int"),
    ("euleris_N7", "int"),
    ("euleris_N8", "int"),
    ("euleris_N9", "int"),
    ("euleris_N10", "int"),
    ("euleris_cycles", "int"),
    ("euleris_logP", "float"),
    ("euleris_esol", "float"),
    ("euleris_bbbp", "float"),
    ("euleris_tox_score", "int"),
    ("euleris_tox_risk", "str"),
    ("euleris_tox_AhR", "float"),
    ("euleris_tox_ER_LBD", "float"),
    ("euleris_tox_MMP", "float"),
    # V1.4 structural descriptors. rho and its companions are null for
    # molecules outside the 4 to 60 heavy-atom range where rho is computed,
    # and arrive as missing values in KNIME.
    ("euleris_N6_m", "float"),
    ("euleris_phi", "float"),
    ("euleris_rho_lq", "float"),
    ("euleris_rho_pvalue", "float"),
    ("euleris_lambda2", "float"),
    ("euleris_q1", "float"),
]

# Subset emitted by the batch node.
EULERIS_BATCH_COLUMNS = [
    ("euleris_score", "int"),
    ("euleris_N3", "int"),
    ("euleris_N4", "int"),
    ("euleris_N5", "int"),
    ("euleris_N6", "int"),
    ("euleris_N7", "int"),
    ("euleris_N8", "int"),
    ("euleris_N9", "int"),
    ("euleris_N10", "int"),
    ("euleris_tox_score", "int"),
    ("euleris_tox_risk", "str"),
]


def _is_rate_limit(exc: BaseException) -> bool:
    """Detect a euleris RateLimitError WITHOUT importing euleris.

    The KNIME test env does not install euleris, so we match on the
    exception class name (and any base-class name) instead.
    """
    for klass in type(exc).__mro__:
        if klass.__name__ == "RateLimitError":
            return True
    return False


def _empty_spectrum_row() -> dict:
    """A row of new columns all set to pandas NA (used on failure)."""
    return {name: pd.NA for name, _ in EULERIS_OUTPUT_COLUMNS}


def _molecule_to_row(result) -> dict:
    """Extract the EULERIS_OUTPUT_COLUMNS values from a MoleculeResult."""
    row = {}

    spectrum = getattr(result, "spectrum", None) or {}
    row["euleris_score"] = getattr(result, "score", None)

    cycles = 0
    for key in _SPECTRUM_KEYS:
        val = spectrum.get(key, 0)
        row["euleris_" + key] = val
        try:
            cycles += int(val)
        except (TypeError, ValueError):
            pass
    row["euleris_cycles"] = cycles

    # ADME predictions (dict[str, AdmePrediction] or None).
    predictions = getattr(result, "predictions", None) or {}
    for src_key, col in _ADME_KEYS.items():
        pred = predictions.get(src_key)
        row[col] = getattr(pred, "value", None) if pred is not None else pd.NA

    # Toxicity (ToxicityPrediction or None).
    tox = getattr(result, "toxicity", None)
    if tox is not None:
        row["euleris_tox_score"] = getattr(tox, "score", None)
        row["euleris_tox_risk"] = getattr(tox, "risk", None)
        endpoints = getattr(tox, "endpoints", None) or {}
        for src_key, col in _TOX_ENDPOINTS.items():
            ep = endpoints.get(src_key)
            row[col] = getattr(ep, "probability", None) if ep is not None else pd.NA
    else:
        row["euleris_tox_score"] = pd.NA
        row["euleris_tox_risk"] = pd.NA
        for col in _TOX_ENDPOINTS.values():
            row[col] = pd.NA

    # V1.4 descriptors. Absent on a pre-V1.4 API, and `spectral` is None for
    # molecules outside the size range where rho is computed; both become NA.
    density = getattr(result, "spectrum_density", None) or {}
    row["euleris_N6_m"] = density.get("N6_m", pd.NA)
    phi = getattr(result, "phi", None)
    row["euleris_phi"] = pd.NA if phi is None else phi

    spectral = getattr(result, "spectral", None)
    for col, attr in (
        ("euleris_rho_lq", "rho_lq"),
        ("euleris_rho_pvalue", "rho_lq_pvalue"),
        ("euleris_lambda2", "lambda2"),
        ("euleris_q1", "q1"),
    ):
        value = getattr(spectral, attr, None) if spectral is not None else None
        row[col] = pd.NA if value is None else value

    return row


def enrich_spectrum(df, smiles_col, analyze_fn, progress_cb=None, warn_cb=None):
    """Enrich ``df`` with per-molecule Euleris spectrum + ADME + toxicity.

    For each row, call ``analyze_fn(smiles)`` and append the
    EULERIS_OUTPUT_COLUMNS. On ANY per-row exception (invalid SMILES,
    etc.) the new columns for that row are filled with NA, ``warn_cb`` is
    called, and processing continues. A rate-limit error is re-raised
    immediately.

    Parameters
    ----------
    df : pandas.DataFrame
    smiles_col : str
    analyze_fn : callable(smiles) -> MoleculeResult
    progress_cb : callable(i, n), optional
    warn_cb : callable(str), optional
    """
    n = len(df)
    rows = []
    for i, smiles in enumerate(df[smiles_col].tolist()):
        try:
            result = analyze_fn(smiles)
            rows.append(_molecule_to_row(result))
        except Exception as exc:  # noqa: BLE001
            if _is_rate_limit(exc):
                raise
            if warn_cb is not None:
                warn_cb(f"Euleris analysis failed for '{smiles}': {exc}")
            rows.append(_empty_spectrum_row())
        if progress_cb is not None:
            progress_cb(i + 1, n)

    new_cols = pd.DataFrame(rows, index=df.index, columns=[c for c, _ in EULERIS_OUTPUT_COLUMNS])
    return pd.concat([df, new_cols], axis=1)


def chunk_indices(n, size):
    """Return a list of (start, end) slices covering ``range(n)``.

    ``size`` is clamped to ``[1, 1000]``.
    """
    size = int(size)
    if size < 1:
        size = 1
    elif size > 1000:
        size = 1000
    if n <= 0:
        return []
    return [(start, min(start + size, n)) for start in range(0, n, size)]


def _batch_item_to_row(item) -> dict:
    """Extract the EULERIS_BATCH_COLUMNS values from a BatchMolecule."""
    spectrum = getattr(item, "spectrum", None) or {}
    row = {"euleris_score": getattr(item, "score", None)}
    for key in _SPECTRUM_KEYS:
        row["euleris_" + key] = spectrum.get(key, 0)
    row["euleris_tox_score"] = getattr(item, "tox_score", None)
    row["euleris_tox_risk"] = getattr(item, "tox_risk", None)
    return row


def _empty_batch_row() -> dict:
    return {name: pd.NA for name, _ in EULERIS_BATCH_COLUMNS}


def enrich_batch(df, smiles_col, batch_fn, batch_size=100, progress_cb=None):
    """Enrich ``df`` using the Euleris batch endpoint.

    The SMILES column is chunked via ``chunk_indices``; ``batch_fn(chunk)``
    is called per chunk and results are mapped back BY SMILES (a chunk may
    drop invalid molecules, so alignment is on the SMILES string; anything
    missing is NA-filled). Appends EULERIS_BATCH_COLUMNS.

    Parameters
    ----------
    df : pandas.DataFrame
    smiles_col : str
    batch_fn : callable(list[str]) -> BatchResult
    batch_size : int
    progress_cb : callable(i, n), optional
    """
    smiles_list = df[smiles_col].tolist()
    n = len(smiles_list)
    slices = chunk_indices(n, batch_size)

    # smiles -> row of new columns.
    by_smiles = {}
    for done, (start, end) in enumerate(slices):
        chunk = smiles_list[start:end]
        result = batch_fn(chunk)
        for item in getattr(result, "results", None) or []:
            by_smiles[getattr(item, "smiles", None)] = _batch_item_to_row(item)
        if progress_cb is not None:
            progress_cb(done + 1, len(slices))

    rows = [by_smiles.get(s, _empty_batch_row()) for s in smiles_list]
    new_cols = pd.DataFrame(rows, index=df.index, columns=[c for c, _ in EULERIS_BATCH_COLUMNS])
    return pd.concat([df, new_cols], axis=1)


# ─── V2.0: reactivity (bond fragility + degradation network) ───

# Output port 1: one row per bond per input molecule.
BOND_FRAGILITY_COLUMNS = [
    ("input_smiles", "str"),
    ("bond_idx", "int"),
    ("atom_i", "int"),
    ("atom_j", "int"),
    ("symbol_i", "str"),
    ("symbol_j", "str"),
    ("bond_type", "str"),
    ("status", "str"),
    ("phi", "float"),
    ("delta_lambda2", "float"),
    ("is_bridge", "bool"),
]

# Appended to port 1 only when a reagent was supplied.
REAGENT_COLUMN = ("reagent_targeted", "bool")

# Output port 2: one row per FRAGMENT. A fragmentation that cuts a bridge
# yields two fragments, and the fragment_smiles / fragment_score columns are
# single-valued, so one row per fragment is the only faithful shape. Rows for
# the same cut share a bond_idx.
DEGRADATION_COLUMNS = [
    ("input_smiles", "str"),
    ("bond_idx", "int"),
    ("bond_atoms", "str"),
    ("is_af", "bool"),
    ("fragment_smiles", "str"),
    ("fragment_score", "int"),
    ("delta_score", "int"),
    ("breaks_ring", "bool"),
]


def call_reactivity(smiles, api_key, reagent_smiles=None):
    """Call the reactivity endpoint through the euleris pip package.

    Imported locally so this module stays importable without euleris
    installed, which is what lets the tests run outside a KNIME environment.
    """
    import euleris

    euleris.configure(api_key=api_key)
    return euleris.reactivity(smiles, reagent_smiles)


def _bond_rows(smiles, result, with_reagent):
    """Port 1 rows for one molecule."""
    targeted = set()
    match = getattr(result, "reagent_match", None)
    if match is not None:
        targeted = set(getattr(match, "bonds_targeted", None) or [])

    rows = []
    for bond in getattr(result, "bonds", None) or []:
        atoms = getattr(bond, "atoms", None) or []
        symbols = getattr(bond, "symbols", None) or []
        row = {
            "input_smiles": smiles,
            "bond_idx": getattr(bond, "bond_idx", pd.NA),
            "atom_i": atoms[0] if len(atoms) > 0 else pd.NA,
            "atom_j": atoms[1] if len(atoms) > 1 else pd.NA,
            "symbol_i": symbols[0] if len(symbols) > 0 else pd.NA,
            "symbol_j": symbols[1] if len(symbols) > 1 else pd.NA,
            "bond_type": getattr(bond, "bond_type", pd.NA),
            # A bond on no cycle is always-fragile: nothing routes around it.
            "status": "AF" if getattr(bond, "is_af", False) else "SOLID",
            "phi": getattr(bond, "phi", pd.NA),
            "delta_lambda2": getattr(bond, "delta_lambda2", pd.NA),
            "is_bridge": getattr(bond, "is_bridge", pd.NA),
        }
        if with_reagent:
            row[REAGENT_COLUMN[0]] = getattr(bond, "bond_idx", None) in targeted
        rows.append(row)
    return rows


def _degradation_rows(smiles, result):
    """Port 2 rows for one molecule, one per fragment."""
    rows = []
    for frag in getattr(result, "degradation", None) or []:
        fragments = getattr(frag, "fragments", None) or []
        common = {
            "input_smiles": smiles,
            "bond_idx": getattr(frag, "bond_idx", pd.NA),
            "bond_atoms": getattr(frag, "bond_atoms", pd.NA),
            "is_af": getattr(frag, "is_af", pd.NA),
            "delta_score": getattr(frag, "delta_score", pd.NA),
            "breaks_ring": getattr(frag, "breaks_ring", pd.NA),
        }
        if not fragments:
            # RDKit refused to sanitize the pieces; keep the cut on the record.
            rows.append({**common, "fragment_smiles": pd.NA, "fragment_score": pd.NA})
            continue
        for piece in fragments:
            rows.append(
                {
                    **common,
                    "fragment_smiles": getattr(piece, "smiles", pd.NA),
                    "fragment_score": getattr(piece, "score", pd.NA),
                }
            )
    return rows


def build_reactivity_tables(
    df,
    smiles_col,
    reactivity_fn,
    reagent_smiles=None,
    progress_cb=None,
    warn_cb=None,
):
    """Run reactivity over a SMILES column and build both output tables.

    Returns ``(bond_fragility_df, degradation_df)``. A row whose SMILES fails
    is skipped with a warning and contributes no rows to either table, so an
    invalid molecule never produces misleading bond data. A rate-limit error
    is re-raised immediately: retrying the remaining rows would only burn
    quota.

    Parameters
    ----------
    df : pandas.DataFrame
    smiles_col : str
    reactivity_fn : callable(smiles, reagent_smiles) -> ReactivityResult
    reagent_smiles : str or None
    progress_cb : callable(i, n), optional
    warn_cb : callable(str), optional
    """
    with_reagent = bool(reagent_smiles)
    bond_columns = [c for c, _ in BOND_FRAGILITY_COLUMNS]
    if with_reagent:
        bond_columns = bond_columns + [REAGENT_COLUMN[0]]

    smiles_list = df[smiles_col].tolist()
    n = len(smiles_list)
    bond_rows, degradation_rows = [], []

    for i, smiles in enumerate(smiles_list):
        try:
            result = reactivity_fn(smiles, reagent_smiles)
            bond_rows.extend(_bond_rows(smiles, result, with_reagent))
            degradation_rows.extend(_degradation_rows(smiles, result))
        except Exception as exc:  # noqa: BLE001
            if _is_rate_limit(exc):
                raise
            if warn_cb is not None:
                warn_cb(f"Euleris reactivity failed for '{smiles}': {exc}")
        if progress_cb is not None:
            progress_cb(i + 1, n)

    bonds = pd.DataFrame(bond_rows, columns=bond_columns)
    degradation = pd.DataFrame(
        degradation_rows, columns=[c for c, _ in DEGRADATION_COLUMNS]
    )
    return bonds, degradation
