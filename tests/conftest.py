from __future__ import annotations

import pytest


@pytest.fixture
def anyio_backend() -> str:
    """Run the asyncio-specific Runtime suite only on its supported backend."""
    return "asyncio"
