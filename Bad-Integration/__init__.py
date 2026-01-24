from .bad_integration import bad_integration
import logging
import os

# This should be minimal but has extra code
logger = logging.getLogger(__name__)
print("Loading bad integration...")

__all__ = ["bad_integration"]
