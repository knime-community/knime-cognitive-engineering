"""KNIME node classes for Euleris (thin wrappers around euleris PyPI).

Every heavy data transformation lives in ``_logic.py`` (pure pandas, no
KNIME import). These node classes only: read config, convert the input
table to pandas, call the pure logic function (injecting ``euleris.analyze``
/ ``euleris.batch`` and progress/warn callbacks), and convert the result
back to a ``knext.Table``.
"""

import logging

import knime.extension as knext

from ._logic import (
    BOND_FRAGILITY_COLUMNS,
    DEGRADATION_COLUMNS,
    EULERIS_BATCH_COLUMNS,
    EULERIS_OUTPUT_COLUMNS,
    REAGENT_COLUMN,
    build_reactivity_tables,
    call_reactivity,
    enrich_batch,
    enrich_spectrum,
)

LOGGER = logging.getLogger(__name__)

UPGRADE_URL = "https://cognitive-engineering.dev/pricing"

# No `category=` on the nodes below: KNIME 5.x forbids dev-loaded Python
# extensions from creating categories, so nodes show under "Uncategorized" until
# published via the Community Extensions program.

# Map _logic dtype strings -> knext ktypes for schema construction.
_KTYPES = {
    "int": knext.int64(),
    "float": knext.double(),
    "str": knext.string(),
    "bool": knext.bool_(),
}


def _schema_from(columns):
    """Build a standalone knext schema from (name, dtype) pairs."""
    return knext.Schema(
        [_KTYPES[dtype] for _, dtype in columns], [name for name, _ in columns]
    )


def _append_columns(schema, columns):
    """Append (name, dtype) columns to a knext schema."""
    for name, dtype in columns:
        schema = schema.append(knext.Column(_KTYPES[dtype], name))
    return schema


def _is_rate_limit(exc):
    for klass in type(exc).__mro__:
        if klass.__name__ == "RateLimitError":
            return True
    return False


@knext.node(
    name="Euleris Spectrum",
    node_type=knext.NodeType.MANIPULATOR,
    icon_path="icons/euleris.png",
)
@knext.input_table(name="Molecules", description="Table with a SMILES column.")
@knext.output_table(
    name="Enriched molecules",
    description="Input table with appended Euleris spectrum, ADME and toxicity columns.",
)
class EulerisSpectrumNode:
    """Euleris Spectrum - topological molecular analysis.

    Computes the cycle spectrum (N3..N10), a topological complexity score,
    ADME predictions (logP, ESOL, BBBP) and toxicity risk for each molecule
    in the SMILES column. Analysis runs server-side via the live Euleris API.
    """

    smiles_column = knext.ColumnParameter(
        label="SMILES column",
        description="Column holding the molecule SMILES strings.",
        port_index=0,
    )
    api_key = knext.StringParameter(
        label="API Key",
        description="Your Euleris API key (starts with ek_).",
        default_value="",
    )

    def configure(self, config_context, input_schema):
        return _append_columns(input_schema, EULERIS_OUTPUT_COLUMNS)

    def execute(self, exec_context, input_table):
        import euleris

        euleris.configure(api_key=self.api_key)
        df = input_table.to_pandas()

        try:
            result = enrich_spectrum(
                df,
                self.smiles_column,
                euleris.analyze,
                progress_cb=lambda i, n: exec_context.set_progress(i / n if n else 1.0),
                warn_cb=lambda m: LOGGER.warning(m),
            )
        except Exception as exc:  # noqa: BLE001
            if _is_rate_limit(exc):
                raise RuntimeError(
                    f"Euleris daily limit reached. {exc} Upgrade at {UPGRADE_URL}"
                ) from exc
            raise

        return knext.Table.from_pandas(result)


@knext.node(
    name="Euleris Batch",
    node_type=knext.NodeType.MANIPULATOR,
    icon_path="icons/euleris.png",
)
@knext.input_table(name="Molecules", description="Table with a SMILES column.")
@knext.output_table(
    name="Enriched molecules",
    description="Input table with appended Euleris spectrum and toxicity columns (batch mode).",
)
class EulerisBatchNode:
    """Euleris Batch - high-throughput topological molecular analysis.

    Enriches a large SMILES table using the Euleris batch endpoint, sending
    molecules in chunks. Appends the cycle spectrum (N3..N10), the complexity
    score and toxicity risk. Analysis runs server-side via the live API.
    """

    smiles_column = knext.ColumnParameter(
        label="SMILES column",
        description="Column holding the molecule SMILES strings.",
        port_index=0,
    )
    api_key = knext.StringParameter(
        label="API Key",
        description="Your Euleris API key (starts with ek_).",
        default_value="",
    )
    batch_size = knext.IntParameter(
        label="Batch Size",
        description="Number of molecules sent per API request.",
        default_value=100,
        min_value=1,
        max_value=1000,
    )

    def configure(self, config_context, input_schema):
        return _append_columns(input_schema, EULERIS_BATCH_COLUMNS)

    def execute(self, exec_context, input_table):
        import euleris

        euleris.configure(api_key=self.api_key)
        df = input_table.to_pandas()

        try:
            result = enrich_batch(
                df,
                self.smiles_column,
                euleris.batch,
                batch_size=self.batch_size,
                progress_cb=lambda i, n: exec_context.set_progress(i / n if n else 1.0),
            )
        except Exception as exc:  # noqa: BLE001
            if _is_rate_limit(exc):
                raise RuntimeError(
                    f"Euleris daily limit reached. {exc} Upgrade at {UPGRADE_URL}"
                ) from exc
            raise

        return knext.Table.from_pandas(result)


@knext.node(
    name="Euleris Reactivity",
    node_type=knext.NodeType.MANIPULATOR,
    icon_path="icons/euleris.png",
)
@knext.input_table(name="Input Table", description="Table with a SMILES column.")
@knext.output_table(
    name="Bond Fragility",
    description="One row per bond: always-fragile or solid, phi, delta-lambda2.",
)
@knext.output_table(
    name="Degradation Network",
    description="One row per fragment produced by breaking each bond in turn.",
)
class EulerisReactivityNode:
    """Euleris Reactivity - bond fragility and degradation analysis.

    Classifies every bond of every input molecule as always-fragile (it lies
    on no cycle, so breaking it has no topological bypass) or solid, then
    breaks each bond in turn and reports the resulting fragments with their
    topological score.

    Supplying a reagent SMILES also marks which bonds that reagent is
    predicted to attack. Matching is ORD-backed where the reagent is known
    and falls back to a structural heuristic otherwise; the confidence of
    that call is visible in the Euleris web app. Analysis runs server-side
    via the live Euleris API.
    """

    smiles_column = knext.ColumnParameter(
        label="SMILES column",
        description="Column holding the molecule SMILES strings.",
        port_index=0,
    )
    api_key = knext.StringParameter(
        label="API Key",
        description="Your Euleris API key (starts with ek_).",
        default_value="",
    )
    reagent_smiles = knext.StringParameter(
        label="Reagent SMILES",
        description=(
            "Optional. A reagent SMILES, or UV for photolysis. Leave empty for "
            "fragility and degradation only."
        ),
        default_value="",
    )

    def configure(self, config_context, input_schema):
        bond_columns = list(BOND_FRAGILITY_COLUMNS)
        if self.reagent_smiles.strip():
            bond_columns.append(REAGENT_COLUMN)
        return _schema_from(bond_columns), _schema_from(DEGRADATION_COLUMNS)

    def execute(self, exec_context, input_table):
        df = input_table.to_pandas()
        reagent = self.reagent_smiles.strip() or None
        api_key = self.api_key

        try:
            bonds, degradation = build_reactivity_tables(
                df,
                self.smiles_column,
                lambda smiles, reagent_smiles: call_reactivity(
                    smiles, api_key, reagent_smiles
                ),
                reagent_smiles=reagent,
                progress_cb=lambda i, n: exec_context.set_progress(i / n if n else 1.0),
                warn_cb=lambda m: LOGGER.warning(m),
            )
        except Exception as exc:  # noqa: BLE001
            if _is_rate_limit(exc):
                raise RuntimeError(
                    f"Euleris daily limit reached. {exc} Upgrade at {UPGRADE_URL}"
                ) from exc
            raise

        return knext.Table.from_pandas(bonds), knext.Table.from_pandas(degradation)
