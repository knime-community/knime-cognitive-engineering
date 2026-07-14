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
    EULERIS_BATCH_COLUMNS,
    EULERIS_OUTPUT_COLUMNS,
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
}


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
    """Euleris Spectrum — topological molecular analysis.

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
    """Euleris Batch — high-throughput topological molecular analysis.

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
