"""
Test file with invalid imported names.

These imports reference names that don't exist within valid modules.
The modules exist, but the specific names do not.
"""

from os import nonexistent_function, fake_constant
from os.path import imaginary_join, not_a_real_function
from json import parse_something, encode_magic
