import pytest


pytestmark = pytest.mark.unit


def test_fixture_is_available_for_validation():
    """Keep unit execution independent from the intentional SDK-pin failure."""
