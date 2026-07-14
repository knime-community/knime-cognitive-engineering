"""GraphCoherence KNIME extension registration.

KNIME imports this package to register the nodes (``from . import nodes``).
The node module needs ``knime.extension``, which only exists inside the
KNIME runtime; guarding the import keeps ``graphcoherence_knime._logic``
importable (and unit-testable) in a plain Python env where ``knime`` is
absent.
"""

try:
    from . import nodes  # noqa: F401
except ModuleNotFoundError as exc:  # pragma: no cover
    if exc.name not in ("knime", "knime.extension"):
        raise
