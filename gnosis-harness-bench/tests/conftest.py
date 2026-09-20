from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture(scope="session")
def dataset():
    from bench.cases import load_dataset

    return load_dataset(FIXTURES)


@pytest.fixture(scope="session")
def ingestion_cases(dataset):
    from bench.cases import build_cases

    return build_cases(dataset, "ingestion")


@pytest.fixture(scope="session")
def verdict_cases(dataset):
    from bench.cases import build_cases

    return build_cases(dataset, "verdict")


@pytest.fixture(scope="session")
def verdict_case_by_id(verdict_cases):
    return {c["case_id"]: c for c in verdict_cases}
