"""Tests for graphcoherence_knime._logic (pure functions, no KNIME)."""

import math

import pandas as pd

from graphcoherence_knime._logic import (
    EDGE_OUTPUT_COLUMNS,
    SUMMARY_OUTPUT_COLUMNS,
    build_edge_table,
    build_summary_table,
    extract_edges,
)


class FakePreviewResult:
    def __init__(self, edge_results, mean_ricci=None, ricci_regime=None):
        self.edge_results = edge_results
        self.mean_ricci = mean_ricci
        self.ricci_regime = ricci_regime


def _edge(source, target, tri, state, ccrit, ricci=None):
    return {
        "edge_key": f"{source}-{target}",
        "source": source,
        "target": target,
        "tri": tri,
        "ccrit": ccrit,
        "ceff": 0.0,
        "state": state,
        "ricci": ricci,
    }


def test_extract_edges():
    df = pd.DataFrame({"src": [1, 2, 3], "dst": [2, 3, 1]})
    assert extract_edges(df, "src", "dst") == [(1, 2), (2, 3), (3, 1)]


def test_build_edge_table_columns_and_values():
    result = FakePreviewResult([
        _edge(1, 2, tri=3, state="solid", ccrit=0.27, ricci=0.5),
        _edge(2, 3, tri=0, state="always_fragile", ccrit=math.inf, ricci=-0.2),
    ])
    out = build_edge_table(result)

    assert list(out.columns) == [c for c, _ in EDGE_OUTPUT_COLUMNS]

    r0 = out.iloc[0]
    assert r0["source"] == 1
    assert r0["target"] == 2
    assert r0["edge_key"] == "1-2"
    assert r0["gc_tri_count"] == 3
    assert r0["gc_state"] == "solid"
    assert r0["gc_ricci"] == 0.5
    assert r0["gc_ccrit"] == 0.27

    # inf ccrit -> NA
    r1 = out.iloc[1]
    assert r1["gc_state"] == "always_fragile"
    assert r1["gc_tri_count"] == 0
    assert pd.isna(r1["gc_ccrit"])
    assert r1["gc_ricci"] == -0.2


def test_build_edge_table_tolerant_of_missing_keys():
    result = FakePreviewResult([{"source": 1, "target": 2}])
    out = build_edge_table(result)
    assert out.iloc[0]["gc_tri_count"] == 0
    assert pd.isna(out.iloc[0]["gc_ccrit"])
    assert pd.isna(out.iloc[0]["gc_ricci"])


def test_build_summary_table():
    edges = [(1, 2), (2, 3), (3, 1), (3, 4)]
    result = FakePreviewResult(
        [
            _edge(1, 2, tri=2, state="solid", ccrit=0.4),
            _edge(2, 3, tri=1, state="pre", ccrit=0.8),
            _edge(3, 1, tri=0, state="always_fragile", ccrit=math.inf),
            _edge(3, 4, tri=0, state="always_fragile", ccrit=math.inf),
        ],
        mean_ricci=0.15,
        ricci_regime="hyperbolic",
    )
    out = build_summary_table(result, edges)

    assert list(out.columns) == [c for c, _ in SUMMARY_OUTPUT_COLUMNS]
    row = out.iloc[0]
    # 2 of 4 edges have tri==0
    assert row["gc_fi"] == 0.5
    # unique nodes: {1,2,3,4}
    assert row["gc_nodes"] == 4
    assert row["gc_edges"] == 4
    # tri>0 count = 2
    assert row["gc_triangles"] == 2
    assert row["gc_mean_ricci"] == 0.15
    assert row["gc_regime"] == "hyperbolic"
    # min tri = 0
    assert row["gc_regime_tau"] == 0


def test_build_summary_table_empty():
    out = build_summary_table(FakePreviewResult([]), [])
    row = out.iloc[0]
    assert pd.isna(row["gc_fi"])
    assert row["gc_nodes"] == 0
    assert row["gc_edges"] == 0
    assert row["gc_triangles"] == 0
