import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def _clear_cache():
    """Each test starts with an empty cache so cached upstream responses never leak between tests."""
    cache.clear()
    yield
    cache.clear()
