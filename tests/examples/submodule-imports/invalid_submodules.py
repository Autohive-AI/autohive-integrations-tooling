"""
Test file with invalid submodule imports.

These imports should fail validation because the submodules don't exist,
even though the top-level packages do.
"""

import os.nonexistent_submodule
import collections.fake_module

from urllib.does_not_exist import something
