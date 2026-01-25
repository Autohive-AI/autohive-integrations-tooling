"""
Test file with invalid relative imports.

These relative imports reference non-existent modules.
"""

from . import nonexistent_sibling  # No such sibling module
from .. import fake_module  # No such module in parent
from ...outside import something  # Goes beyond package root
