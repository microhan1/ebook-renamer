"""pytest: every test runs with the production-server guard, and a test that tried to reach
chaekgalpi.co.kr fails. Tests of the update notice inject their own answers (fetcher=, a fake
opener, or a patched update_check.fetch) and are not affected."""
from __future__ import annotations

import pytest

from . import _netguard


@pytest.fixture(autouse=True)
def no_production_server():
    _netguard.install()            # put it back in case a test replaced something
    _netguard.take()
    yield
    tried = _netguard.take()
    if tried:
        pytest.fail(f"this test tried to reach the production server {len(tried)} time(s): {tried[:3]}", pytrace=False)
