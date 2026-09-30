"""Shared fixtures.

Every test runs on the made-up data in tests/fixture_data.py, so the suite
needs no download and passes from a clean checkout. Tests that need the engine
skip themselves where the `samyama` package is not installed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from etl import loader  # noqa: E402
from tests.fixture_data import write_raw  # noqa: E402

SEED = 20260929
SCALE = 0.05


@pytest.fixture(scope="session")
def raw_dir(tmp_path_factory) -> Path:
    return write_raw(tmp_path_factory.mktemp("data") / "raw")


@pytest.fixture(scope="session")
def real_graph(raw_dir):
    nodes, edges, dropped = loader.build("real", raw_dir=raw_dir)
    return nodes, edges, dropped


@pytest.fixture(scope="session")
def full_graph(raw_dir):
    nodes, edges, dropped = loader.build("all", seed=SEED, scale=SCALE, raw_dir=raw_dir)
    return nodes, edges, dropped


@pytest.fixture(scope="session")
def engine(raw_dir):
    """The fixture graph, loaded into an embedded engine and verified."""
    pytest.importorskip("samyama", reason="the Samyama engine is not installed")
    client, nodes, edges = loader.load_embedded("all", seed=SEED, scale=SCALE,
                                                raw_dir=raw_dir)
    return client, nodes, edges
