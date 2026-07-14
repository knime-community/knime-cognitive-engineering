"""Pure data logic for the Euleris KNIME nodes.

This module contains NO ``import knime`` — every function here is a plain
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
