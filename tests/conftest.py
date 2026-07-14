"""Make ``src`` importable so tests can ``import euleris_knime._logic``.

Tests import ONLY the ``_logic`` modules (never ``nodes.py``, which
requires the KNIME runtime that is not installed in this env).
"""

import os
import sys

_SRC = os.path.join(os.path.dirname(os.path.dirname(__file__)), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
