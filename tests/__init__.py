"""Test package. Importing it puts the production-server guard in place for every runner
(``python -m unittest tests.test_ui`` and pytest alike); see _netguard.py."""
from . import _netguard  # noqa: F401  (installs the guard on import)
