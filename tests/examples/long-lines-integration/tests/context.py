import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from long_lines_integration import long_lines_integration  # noqa: F401, E402
