"""KNIME node classes for GraphCoherence (thin wrappers around the PyPI pkg).

Data logic lives in ``_logic.py`` (pure pandas, no KNIME import). These
node classes only read config, convert tables, call the pure logic
functions (injecting ``gc.preview``), and convert results back.
"""

import logging

import knime.extension as knext

from ._logic import (
    EDGE_OUTPUT_COLUMNS,
    SUMMARY_OUTPUT_COLUMNS,
    build_edge_table,
    build_summary_table,
    extract_edges,
)

LOGGER = logging.getLogger(__name__)

UPGRADE_URL = "https://cognitive-engineering.dev/pricing"

# No `category=` on the node below: KNIME 5.x forbids dev-loaded Python
# extensions from creating categories, so nodes show under "Uncategorized" until
# published via the Community Extensions program.

_KTYPES = {
    "int": knext.int64(),
    "float": knext.double(),
    "str": knext.string(),
}


def _schema_from_columns(columns):
    return knext.Schema(
        [_KTYPES[dtype] for _, dtype in columns],
        [name for name, _ in columns],
    )


def _is_rate_limit(exc):
    for klass in type(exc).__mro__:
        if klass.__name__ == "RateLimitError":
            return True
    return False


@knext.node(
    name="GraphCoherence Analyzer",
    node_type=knext.NodeType.MANIPULATOR,
    icon_path="icons/graphcoherence.png",
)
@knext.input_table(
    name="Edge list",
    description="Table with a source and a target column defining the network edges.",
)
@knext.output_table(
    name="Edge table",
    description="Per-edge classification: triangle count, state, Ricci curvature, critical coupling.",
)
@knext.output_table(
    name="Network summary",
    description="Single-row network summary: fragility index, node/edge/triangle counts, Ricci regime.",
)
class GraphCoherenceAnalyzerNode:
    """GraphCoherence Analyzer - structural network analysis.

    Classifies every edge of a network by its local triangle motif count and
    stability state (solid / pre / always-fragile), optionally with Ollivier-
    Ricci curvature, and reports a network-level summary. Analysis runs
    server-side via the live GraphCoherence API.
    """

    source_column = knext.ColumnParameter(
        label="Source column",
        description="Column with the edge source node id (int or string).",
        port_index=0,
    )
    target_column = knext.ColumnParameter(
        label="Target column",
        description="Column with the edge target node id (int or string).",
        port_index=0,
    )
    api_key = knext.StringParameter(
        label="API Key",
        description="Your GraphCoherence API key.",
        default_value="",
    )
    c_param = knext.DoubleParameter(
        label="C parameter",
        description="Coherence coupling threshold for the preview classification.",
        default_value=0.0,
    )

    def configure(self, config_context, input_schema):
        return (
            _schema_from_columns(EDGE_OUTPUT_COLUMNS),
            _schema_from_columns(SUMMARY_OUTPUT_COLUMNS),
        )

    def execute(self, exec_context, input_table):
        import graphcoherence as gc

        gc.configure(api_key=self.api_key)
        df = input_table.to_pandas()
        edges = extract_edges(df, self.source_column, self.target_column)

        try:
            result = gc.preview(edges=edges, C=self.c_param)
        except Exception as exc:  # noqa: BLE001
            if _is_rate_limit(exc):
                raise RuntimeError(
                    f"GraphCoherence daily limit reached. {exc} Upgrade at {UPGRADE_URL}"
                ) from exc
            raise

        return (
            knext.Table.from_pandas(build_edge_table(result)),
            knext.Table.from_pandas(build_summary_table(result, edges)),
        )
