"""Tests for the V1.4 descriptor columns and the V2.0 Reactivity node logic.

Like the other node tests these exercise ``_logic`` only: ``nodes.py`` needs
the KNIME runtime, which is not installed in this environment.
"""

import pandas as pd
import pytest

from euleris_knime._logic import (
    BOND_FRAGILITY_COLUMNS,
    DEGRADATION_COLUMNS,
    EULERIS_OUTPUT_COLUMNS,
    REAGENT_COLUMN,
    build_reactivity_tables,
    enrich_spectrum,
)


class RateLimitError(Exception):
    """Same class name as euleris.exceptions.RateLimitError."""


# ─── V1.4 descriptor columns ───

class FakeSpectral:
    def __init__(self, rho_lq=0.45, rho_lq_pvalue=0.09, lambda2=0.09, q1=4.92):
        self.rho_lq = rho_lq
        self.rho_lq_pvalue = rho_lq_pvalue
        self.lambda2 = lambda2
        self.q1 = q1


class FakeMoleculeV14:
    def __init__(self, spectrum, score, spectrum_density=None, phi=None, spectral=None):
        self.spectrum = spectrum
        self.score = score
        self.predictions = None
        self.toxicity = None
        self.spectrum_density = spectrum_density
        self.phi = phi
        self.spectral = spectral


class FakeMoleculeLegacy:
    """A pre-V1.4 response: the descriptor attributes do not exist at all."""

    def __init__(self):
        self.spectrum = {"N6": 1}
        self.score = 42
        self.predictions = None
        self.toxicity = None


def _v14_molecule(spectral=None, phi=0.4, density=None):
    return FakeMoleculeV14(
        spectrum={"N3": 0, "N4": 0, "N5": 0, "N6": 1, "N7": 0, "N8": 0, "N9": 0, "N10": 0},
        score=60,
        spectrum_density=density if density is not None else {"N6_m": 0.066667},
        phi=phi,
        spectral=spectral,
    )


def test_v14_columns_appended_in_order():
    names = [c for c, _ in EULERIS_OUTPUT_COLUMNS]
    assert names[-6:] == [
        "euleris_N6_m",
        "euleris_phi",
        "euleris_rho_lq",
        "euleris_rho_pvalue",
        "euleris_lambda2",
        "euleris_q1",
    ]


def test_v14_values_extracted():
    df = pd.DataFrame({"smiles": ["CC(C)Cc1ccc(cc1)C(C)C(=O)O"]})
    out = enrich_spectrum(df, "smiles", lambda s: _v14_molecule(spectral=FakeSpectral()))
    row = out.iloc[0]
    assert row["euleris_N6_m"] == 0.066667
    assert row["euleris_phi"] == 0.4
    assert row["euleris_rho_lq"] == 0.45
    assert row["euleris_rho_pvalue"] == 0.09
    assert row["euleris_lambda2"] == 0.09
    assert row["euleris_q1"] == 4.92


def test_v14_null_spectral_becomes_missing_value():
    # rho is null outside the 4 to 60 heavy-atom range; phi and the densities
    # still arrive and must survive.
    df = pd.DataFrame({"smiles": ["CCO"]})
    out = enrich_spectrum(df, "smiles", lambda s: _v14_molecule(spectral=None, phi=0.0))
    row = out.iloc[0]
    assert pd.isna(row["euleris_rho_lq"])
    assert pd.isna(row["euleris_rho_pvalue"])
    assert pd.isna(row["euleris_lambda2"])
    assert pd.isna(row["euleris_q1"])
    assert row["euleris_phi"] == 0.0


def test_v14_absent_on_pre_v14_response():
    # An older API omits the fields entirely; the node must degrade, not raise.
    df = pd.DataFrame({"smiles": ["CCO"]})
    out = enrich_spectrum(df, "smiles", lambda s: FakeMoleculeLegacy())
    row = out.iloc[0]
    for col in ("euleris_N6_m", "euleris_phi", "euleris_rho_lq", "euleris_q1"):
        assert pd.isna(row[col])
    assert row["euleris_score"] == 42  # pre-V1.4 columns unaffected


# ─── V2.0 reactivity tables ───

class FakeBond:
    def __init__(self, bond_idx, atoms, symbols, bond_type, is_af, phi, dl2, is_bridge):
        self.bond_idx = bond_idx
        self.atoms = atoms
        self.symbols = symbols
        self.bond_type = bond_type
        self.is_af = is_af
        self.phi = phi
        self.delta_lambda2 = dl2
        self.is_bridge = is_bridge


class FakeFragment:
    def __init__(self, smiles, score):
        self.smiles = smiles
        self.score = score


class FakeFragmentation:
    def __init__(self, bond_idx, bond_atoms, is_af, fragments, delta_score, breaks_ring):
        self.bond_idx = bond_idx
        self.bond_atoms = bond_atoms
        self.is_af = is_af
        self.fragments = fragments
        self.delta_score = delta_score
        self.breaks_ring = breaks_ring


class FakeReagentMatch:
    def __init__(self, bonds_targeted):
        self.bonds_targeted = bonds_targeted


class FakeReactivity:
    def __init__(self, bonds, degradation, reagent_match=None):
        self.bonds = bonds
        self.degradation = degradation
        self.reagent_match = reagent_match


def _biphenyl_reactivity(with_match=False):
    """Two bonds: one ring bond and the inter-ring bridge."""
    bonds = [
        FakeBond(0, [0, 1], ["C", "C"], "AROMATIC", False, 0.5, 0.1, False),
        FakeBond(6, [3, 4], ["C", "C"], "SINGLE", True, 0.0, 0.157, True),
    ]
    degradation = [
        # Opening a ring leaves one fragment.
        FakeFragmentation(
            0, "C-C", False, [FakeFragment("C=CC=CC=Cc1ccccc1", 60)], -15, True
        ),
        # Cutting the bridge splits the molecule in two.
        FakeFragmentation(
            6,
            "C-C",
            True,
            [FakeFragment("c1ccccc1", 65), FakeFragment("c1ccccc1", 65)],
            -10,
            False,
        ),
    ]
    return FakeReactivity(bonds, degradation, FakeReagentMatch([6]) if with_match else None)


def test_bond_table_shape_and_values():
    df = pd.DataFrame({"smiles": ["c1ccc(-c2ccccc2)cc1"]})
    bonds, _ = build_reactivity_tables(df, "smiles", lambda s, r: _biphenyl_reactivity())

    assert list(bonds.columns) == [c for c, _ in BOND_FRAGILITY_COLUMNS]
    assert len(bonds) == 2
    assert list(bonds["status"]) == ["SOLID", "AF"]
    assert list(bonds["bond_idx"]) == [0, 6]
    assert bonds.iloc[1]["atom_i"] == 3
    assert bonds.iloc[1]["atom_j"] == 4
    assert bonds.iloc[1]["symbol_j"] == "C"
    assert bonds.iloc[1]["bond_type"] == "SINGLE"
    assert bool(bonds.iloc[1]["is_bridge"]) is True
    assert bonds.iloc[1]["delta_lambda2"] == 0.157
    assert list(bonds["input_smiles"]) == ["c1ccc(-c2ccccc2)cc1"] * 2


def test_degradation_table_is_one_row_per_fragment():
    df = pd.DataFrame({"smiles": ["c1ccc(-c2ccccc2)cc1"]})
    _, degradation = build_reactivity_tables(
        df, "smiles", lambda s, r: _biphenyl_reactivity()
    )

    assert list(degradation.columns) == [c for c, _ in DEGRADATION_COLUMNS]
    # One fragment for the ring cut, two for the bridge cut.
    assert len(degradation) == 3
    assert list(degradation["bond_idx"]) == [0, 6, 6]
    assert degradation.iloc[1]["fragment_smiles"] == "c1ccccc1"
    assert degradation.iloc[1]["fragment_score"] == 65
    assert bool(degradation.iloc[0]["breaks_ring"]) is True
    assert bool(degradation.iloc[2]["is_af"]) is True
    assert degradation.iloc[0]["delta_score"] == -15


def test_reagent_column_only_present_when_a_reagent_is_given():
    df = pd.DataFrame({"smiles": ["c1ccc(-c2ccccc2)cc1"]})

    without, _ = build_reactivity_tables(df, "smiles", lambda s, r: _biphenyl_reactivity())
    assert REAGENT_COLUMN[0] not in without.columns

    with_reagent, _ = build_reactivity_tables(
        df,
        "smiles",
        lambda s, r: _biphenyl_reactivity(with_match=True),
        reagent_smiles="OO",
    )
    assert REAGENT_COLUMN[0] in with_reagent.columns
    # Only bond 6 was targeted by the reagent.
    assert list(with_reagent[REAGENT_COLUMN[0]]) == [False, True]


def test_reagent_is_passed_through_to_the_api_call():
    df = pd.DataFrame({"smiles": ["CCO"]})
    seen = []

    def fn(smiles, reagent):
        seen.append((smiles, reagent))
        return _biphenyl_reactivity()

    build_reactivity_tables(df, "smiles", fn, reagent_smiles="OO")
    assert seen == [("CCO", "OO")]


def test_multiple_molecules_are_stacked():
    df = pd.DataFrame({"smiles": ["A", "B"]})
    bonds, degradation = build_reactivity_tables(
        df, "smiles", lambda s, r: _biphenyl_reactivity()
    )
    assert len(bonds) == 4
    assert list(bonds["input_smiles"]) == ["A", "A", "B", "B"]
    assert len(degradation) == 6


def test_bad_row_is_skipped_with_a_warning():
    df = pd.DataFrame({"smiles": ["CCO", "not-a-smiles", "c1ccccc1"]})
    warnings = []

    def fn(smiles, reagent):
        if smiles == "not-a-smiles":
            raise ValueError("invalid SMILES")
        return _biphenyl_reactivity()

    bonds, degradation = build_reactivity_tables(df, "smiles", fn, warn_cb=warnings.append)

    # The failed molecule contributes no rows at all, rather than rows of
    # missing values that would read as real bonds.
    assert set(bonds["input_smiles"]) == {"CCO", "c1ccccc1"}
    assert len(bonds) == 4
    assert len(degradation) == 6
    assert len(warnings) == 1
    assert "not-a-smiles" in warnings[0]


def test_rate_limit_propagates():
    df = pd.DataFrame({"smiles": ["CCO"]})

    def fn(smiles, reagent):
        raise RateLimitError("429")

    with pytest.raises(RateLimitError):
        build_reactivity_tables(df, "smiles", fn)


def test_progress_callback_fires_per_row():
    df = pd.DataFrame({"smiles": ["A", "B", "C"]})
    calls = []
    build_reactivity_tables(
        df,
        "smiles",
        lambda s, r: _biphenyl_reactivity(),
        progress_cb=lambda i, n: calls.append((i, n)),
    )
    assert calls == [(1, 3), (2, 3), (3, 3)]


def test_empty_input_yields_empty_tables_with_columns():
    df = pd.DataFrame({"smiles": []})
    bonds, degradation = build_reactivity_tables(
        df, "smiles", lambda s, r: _biphenyl_reactivity()
    )
    assert len(bonds) == 0
    assert len(degradation) == 0
    # The columns must exist regardless, or the node's declared schema and the
    # data it returns would disagree.
    assert list(bonds.columns) == [c for c, _ in BOND_FRAGILITY_COLUMNS]
    assert list(degradation.columns) == [c for c, _ in DEGRADATION_COLUMNS]


def test_fragmentation_without_fragments_is_still_recorded():
    # RDKit occasionally refuses to sanitize the pieces; the cut stays on the
    # record with a missing fragment rather than vanishing.
    frag = FakeFragmentation(3, "C-N", True, [], 0, False)
    result = FakeReactivity([], [frag])
    _, degradation = build_reactivity_tables(
        pd.DataFrame({"smiles": ["X"]}), "smiles", lambda s, r: result
    )
    assert len(degradation) == 1
    assert pd.isna(degradation.iloc[0]["fragment_smiles"])
    assert degradation.iloc[0]["bond_atoms"] == "C-N"
