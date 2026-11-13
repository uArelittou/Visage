import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (str(ROOT), str(Path(__file__).parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

from rating_helpers import Sample  # noqa: E402


@pytest.fixture(scope="session")
def mofa() -> Sample:
    return Sample("mofa")


@pytest.fixture(scope="session")
def lin() -> Sample:
    return Sample("linxiaoye")


@pytest.fixture(scope="session")
def bai() -> Sample:
    return Sample("bailianling")


@pytest.fixture(scope="session")
def fv() -> Sample:
    return Sample("fv125")
