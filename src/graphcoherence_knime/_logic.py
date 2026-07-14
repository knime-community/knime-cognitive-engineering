"""Pure data logic for the GraphCoherence KNIME nodes.

Contains NO ``import knime`` so it is unit-testable without a KNIME
runtime. The node classes in ``nodes.py`` inject the live ``gc.preview``
callable and convert to/from ``knext.Table``.

Preview edge dicts (from the GraphCoherence ``/preview`` engine) carry
the keys: ``edge_key, source, target, tri, ccrit, ceff, state`` plus an
injected ``ricci``. ``state`` is one of ``solid | pre | always_fragile``
and ``ccrit`` may be ``inf`` for always-fragile (tri==0) edges.
"""

from __future__ import annotations

import math

import pandas as pd

EDGE_OUTPUT_COLUMNS = [
    ("source", "str"),
    ("target", "str"),
    ("edge_key", "str"),
    ("gc_tri_count", "int"),
    ("gc_state", "str"),
    ("gc_ricci", "float"),
    ("gc_ccrit", "float"),
]

SUMMARY_OUTPUT_COLUMNS = [
    ("gc_fi", "float"),
    ("gc_nodes", "int"),
    ("gc_edges", "int"),
    ("gc_triangles", "int"),
    ("gc_mean_ricci", "float"),
    ("gc_regime", "str"),
    ("gc_regime_tau", "int"),
]


def extract_edges(df, source_col, target_col):
    """Return a list of ``(source, target)`` tuples from ``df``."""
    return list(zip(df[source_col].tolist(), df[target_col].tolist()))


def _clean_float(value):
    """Return a finite float, or pandas NA for None / inf / non-numeric."""
    if value is None:
        return pd.NA
    try:
        f = float(value)
    except (TypeError, ValueError):
        return pd.NA
    if math.isinf(f) or math.isnan(f):
        return pd.NA
    return f


def _clean_int(value, default=pd.NA):
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def build_edge_table(preview_result):
    """One row per edge in ``preview_result.edge_results``.

    Columns: source, target, edge_key, gc_tri_count, gc_state, gc_ricci,
    gc_ccrit. Tolerant of missing keys (uses ``.get``).
    """
    edges = getattr(preview_result, "edge_results", None) or []
    rows = []
    for e in edges:
        rows.append({
            "source": e.get("source"),
            "target": e.get("target"),
            "edge_key": e.get("edge_key"),
            "gc_tri_count": _clean_int(e.get("tri"), default=0),
            "gc_state": e.get("state"),
            "gc_ricci": _clean_float(e.get("ricci")),
            "gc_ccrit": _clean_float(e.get("ccrit")),
        })
    return pd.DataFrame(rows, columns=[c for c, _ in EDGE_OUTPUT_COLUMNS])


def build_summary_table(preview_result, edges):
    """A single-row network summary DataFrame.

    Parameters
    ----------
    preview_result : PreviewResult-like
    edges : list[tuple]  # the (source, target) pairs sent to the API
    """
    edge_results = getattr(preview_result, "edge_results", None) or []

    tri_values = []
    for e in edge_results:
        tri_values.append(_clean_int(e.get("tri"), default=0))

    total = len(edge_results)
    n_fragile = sum(1 for t in tri_values if t == 0)
    n_triangles = sum(1 for t in tri_values if isinstance(t, int) and t > 0)

    fi = (n_fragile / total) if total else pd.NA

    nodes = set()
    for src, tgt in edges:
        nodes.add(src)
        nodes.add(tgt)

    # regime_tau: prefer the min tri count; fall back to 0.
    numeric_tri = [t for t in tri_values if isinstance(t, int)]
    regime_tau = min(numeric_tri) if numeric_tri else 0

    row = {
        "gc_fi": fi,
        "gc_nodes": len(nodes),
        "gc_edges": len(edges),
        "gc_triangles": n_triangles,
        "gc_mean_ricci": _clean_float(getattr(preview_result, "mean_ricci", None)),
        "gc_regime": getattr(preview_result, "ricci_regime", None),
        "gc_regime_tau": regime_tau,
    }
    return pd.DataFrame([row], columns=[c for c, _ in SUMMARY_OUTPUT_COLUMNS])
