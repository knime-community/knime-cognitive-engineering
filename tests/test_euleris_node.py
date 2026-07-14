"""Tests for euleris_knime._logic (pure functions, no KNIME required)."""

import pandas as pd
import pytest

from euleris_knime._logic import (
    EULERIS_BATCH_COLUMNS,
    EULERIS_OUTPUT_COLUMNS,
    chunk_indices,
    enrich_batch,
    enrich_spectrum,
)


# ── Fakes mimicking euleris models (no live API) ──
class FakeAdme:
    def __init__(self, value, label=None):
        self.value = value
        self.label = label


class FakeToxEndpoint:
    def __init__(self, probability):
        self.probability = probability


class FakeToxicity:
    def __init__(self, score, risk, endpoints):
        self.score = score
        self.risk = risk
        self.endpoints = endpoints


class FakeMolecule:
    def __init__(self, spectrum, score, predictions=None, toxicity=None):
        self.spectrum = spectrum
        self.score = score
        self.predictions = predictions
        self.toxicity = toxicity


class FakeBatchMolecule:
    def __init__(self, smiles, spectrum, score, tox_score=None, tox_risk=None, tox_AhR=None):
        self.smiles = smiles
        self.spectrum = spectrum
        self.score = score
        self.tox_score = tox_score
        self.tox_risk = tox_risk
        self.tox_AhR = tox_AhR


class FakeBatchResult:
    def __init__(self, results):
        self.results = results


class RateLimitError(Exception):
    """Same class name as euleris.exceptions.RateLimitError."""


def _full_molecule():
    return FakeMolecule(
        spectrum={"N3": 1, "N4": 2, "N5": 0, "N6": 3, "N7": 0, "N8": 0, "N9": 0, "N10": 1},
        score=42,
        predictions={
            "logp": FakeAdme(2.5, "moderate"),
            "esol": FakeAdme(-3.1),
            "bbbp": FakeAdme(0.8),
        },
        toxicity=FakeToxicity(
            score=7,
            risk="high",
            endpoints={
                "NR_AhR": FakeToxEndpoint(0.9),
                "NR_ER_LBD": FakeToxEndpoint(0.3),
                "SR_MMP": FakeToxEndpoint(0.5),
            },
        ),
    )


def test_enrich_spectrum_exact_columns_and_values():
    df = pd.DataFrame({"smiles": ["CCO"]})
    out = enrich_spectrum(df, "smiles", lambda s: _full_molecule())

    # Exact output columns appended, in order.
    expected = ["smiles"] + [c for c, _ in EULERIS_OUTPUT_COLUMNS]
    assert list(out.columns) == expected

    row = out.iloc[0]
    assert row["euleris_score"] == 42
    assert row["euleris_N3"] == 1
    assert row["euleris_N6"] == 3
    assert row["euleris_N10"] == 1
    # cycles = sum of N3..N10 = 1+2+0+3+0+0+0+1 = 7
    assert row["euleris_cycles"] == 7
    assert row["euleris_logP"] == 2.5
    assert row["euleris_esol"] == -3.1
    assert row["euleris_bbbp"] == 0.8
    assert row["euleris_tox_score"] == 7
    assert row["euleris_tox_risk"] == "high"
    assert row["euleris_tox_AhR"] == 0.9
    assert row["euleris_tox_ER_LBD"] == 0.3
    assert row["euleris_tox_MMP"] == 0.5


def test_enrich_spectrum_invalid_row_yields_na_and_continues():
    df = pd.DataFrame({"smiles": ["CCO", "not-a-smiles", "c1ccccc1"]})
    warnings = []

    def analyze(s):
        if s == "not-a-smiles":
            raise ValueError("invalid SMILES")
        return _full_molecule()

    out = enrich_spectrum(df, "smiles", analyze, warn_cb=warnings.append)

    # Bad row -> all new columns NA.
    bad = out.iloc[1]
    for name, _ in EULERIS_OUTPUT_COLUMNS:
        assert pd.isna(bad[name])
    # Good rows still populated.
    assert out.iloc[0]["euleris_score"] == 42
    assert out.iloc[2]["euleris_cycles"] == 7
    # warn_cb was called for the bad row.
    assert len(warnings) == 1
    assert "not-a-smiles" in warnings[0]


def test_enrich_spectrum_rate_limit_propagates():
    df = pd.DataFrame({"smiles": ["CCO"]})

    def analyze(s):
        raise RateLimitError("429")

    with pytest.raises(RateLimitError):
        enrich_spectrum(df, "smiles", analyze)


def test_enrich_spectrum_progress_callback():
    df = pd.DataFrame({"smiles": ["A", "B", "C"]})
    calls = []
    enrich_spectrum(df, "smiles", lambda s: _full_molecule(),
                    progress_cb=lambda i, n: calls.append((i, n)))
    assert calls == [(1, 3), (2, 3), (3, 3)]


def test_chunk_indices_edge_cases():
    assert chunk_indices(0, 100) == []
    assert chunk_indices(5, 100) == [(0, 5)]            # n < size
    assert chunk_indices(200, 100) == [(0, 100), (100, 200)]  # exact multiple
    assert chunk_indices(250, 100) == [(0, 100), (100, 200), (200, 250)]
    # size clamped to >=1
    assert chunk_indices(3, 0) == [(0, 1), (1, 2), (2, 3)]
    # size clamped to <=1000
    assert chunk_indices(1500, 5000) == [(0, 1000), (1000, 1500)]


def test_enrich_batch_aligns_by_smiles_and_na_fills():
    df = pd.DataFrame({"smiles": ["A", "BAD", "C"]})

    def batch_fn(chunk):
        # The invalid "BAD" is dropped from the response.
        results = []
        for s in chunk:
            if s == "BAD":
                continue
            results.append(FakeBatchMolecule(
                smiles=s,
                spectrum={"N3": 2, "N4": 0, "N5": 0, "N6": 0, "N7": 0, "N8": 0, "N9": 0, "N10": 0},
                score=10,
                tox_score=1,
                tox_risk="low",
            ))
        return FakeBatchResult(results)

    out = enrich_batch(df, "smiles", batch_fn, batch_size=10)

    expected = ["smiles"] + [c for c, _ in EULERIS_BATCH_COLUMNS]
    assert list(out.columns) == expected

    # Aligned by smiles.
    assert out.iloc[0]["euleris_score"] == 10
    assert out.iloc[0]["euleris_N3"] == 2
    assert out.iloc[0]["euleris_tox_risk"] == "low"
    assert out.iloc[2]["euleris_score"] == 10
    # Dropped invalid -> NA.
    for name, _ in EULERIS_BATCH_COLUMNS:
        assert pd.isna(out.iloc[1][name])


def test_enrich_batch_chunks_and_progress():
    df = pd.DataFrame({"smiles": [str(i) for i in range(5)]})
    seen_chunks = []
    progress = []

    def batch_fn(chunk):
        seen_chunks.append(list(chunk))
        return FakeBatchResult([
            FakeBatchMolecule(smiles=s, spectrum={}, score=0) for s in chunk
        ])

    enrich_batch(df, "smiles", batch_fn, batch_size=2,
                 progress_cb=lambda i, n: progress.append((i, n)))

    assert seen_chunks == [["0", "1"], ["2", "3"], ["4"]]
    assert progress == [(1, 3), (2, 3), (3, 3)]
