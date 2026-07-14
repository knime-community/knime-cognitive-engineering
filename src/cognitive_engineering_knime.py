"""Aggregator extension module for local KNIME dev loading.

Importing the two node packages registers all @knext.node classes (Euleris
Spectrum, Euleris Batch, GraphCoherence Analyzer). Categories are NOT declared
here: KNIME 5.x forbids dev-loaded Python extensions from creating categories
dynamically, so the nodes appear under "Uncategorized" until the extension is
published through the Community Extensions program.
"""

import euleris_knime.nodes  # noqa: F401  (registers Euleris nodes)
import graphcoherence_knime.nodes  # noqa: F401  (registers GraphCoherence node)
