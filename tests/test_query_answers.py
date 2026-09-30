"""Every catalog query, run on the engine and checked against plain Python.

Samyama v1.7.0 returned wrong answers without raising -- unsorted rows,
unenforced joins, dropped rows. So "the query ran" is not a test. Each query
here is answered twice, once by the engine and once by the reference in
benchmarks/reference.py, and the two must agree on the rows, their order, and
which rows a LIMIT kept.

Runs on the made-up fixture graph, which loads in a few seconds. The same check
on the full graph is `python -m benchmarks.run --check`.
"""
from __future__ import annotations

import pytest

from benchmarks.queries import QUERIES, get, render
from benchmarks.reference import REFERENCES, Graph, check, rounded

# The catalog's defaults are tuned to the real data. The fixture is small and
# made up, so some thresholds are lowered to what it contains.
FIXTURE_PARAMS = {
    "FN01": {"from_year": 2000},
    "FN03": {"from_year": 2000},
    "FN04": {"lei": "LEI00000000000000003"},
    "FN09": {"min_usd": 1000.0},
    "FN11": {"min_customers": 2},
    "FN14": {"min_loans": 1},
}


@pytest.fixture(scope="module")
def graph(engine):
    _, nodes, edges = engine
    return Graph(nodes, edges)


def run(engine, query_id, **overrides):
    client, _, _ = engine
    params = {**FIXTURE_PARAMS.get(query_id, {}), **overrides}
    entry = get(query_id)
    return entry, params, client.query_readonly(render(entry, **params), "default").records


@pytest.mark.parametrize("query_id", [q["id"] for q in QUERIES])
def test_engine_agrees_with_the_reference(engine, graph, query_id):
    entry, params, rows = run(engine, query_id)
    assert check(entry, rows, graph, **params) == []


@pytest.mark.parametrize("query_id", [q["id"] for q in QUERIES])
def test_the_fixture_gives_every_query_something_to_answer(engine, query_id):
    """A query that returns nothing agrees with its reference trivially. Each
    must have rows on the fixture, or the test above proves nothing about it."""
    _, _, rows = run(engine, query_id)
    assert rows, f"{query_id} returned no rows on the fixture graph"


@pytest.mark.parametrize("query_id", ["FN02", "FN06", "FN09", "FN12", "FN13", "FN15"])
def test_a_limit_keeps_the_top_rows(engine, graph, query_id):
    """Asked for two, the engine must return the top two, not any two."""
    entry, params, rows = run(engine, query_id, limit=2)
    assert check(entry, rows, graph, **params) == []
    assert len(rows) <= 2


def test_no_query_returns_a_null(engine):
    for q in QUERIES:
        _, _, rows = run(engine, q["id"])
        for row in rows:
            assert None not in row, f"{q['id']} returned a null: {row}"


def test_every_query_has_a_reference():
    assert {q["id"] for q in QUERIES} == set(REFERENCES)


# --------------------------------------------------------------------------
# the checker must be able to fail, or passing means nothing
# --------------------------------------------------------------------------

def test_the_checker_catches_a_wrong_value(engine, graph):
    entry, params, rows = run(engine, "FN02")
    rows[0][1] += 1
    assert any("not in the reference" in p for p in check(entry, rows, graph, **params))


def test_the_checker_catches_a_missing_row(engine, graph):
    entry, params, rows = run(engine, "FN02")
    assert any("rows, expected" in p for p in check(entry, rows[:-1], graph, **params))


def test_the_checker_catches_the_wrong_order(engine, graph):
    entry, params, rows = run(engine, "FN08")
    assert len(rows) >= 2
    assert any("order" in p for p in check(entry, rows[::-1], graph, **params))


def test_the_checker_catches_rows_that_are_not_the_top(engine, graph):
    """Correct rows, correctly ordered, but from the bottom of the ranking."""
    entry = get("FN02")
    everything, keys = REFERENCES["FN02"](graph, limit=10)
    ranked = [row for _, row in sorted(zip(keys, everything, strict=True))]
    assert ranked[0][1] != ranked[-1][1], "the fixture's holding companies all tie"
    problems = check(entry, ranked[-2:], graph, limit=2)
    assert any("not the top" in p for p in problems)


def test_rounding_matches_the_engine(engine):
    client, _, _ = engine
    for value in (0.5, 1.5, 2.5, 2.4999, -0.5, -1.5, 7.0):
        got = client.query_readonly(f"RETURN round({value}) AS r", "default").records[0][0]
        assert got == rounded(value), value


# --------------------------------------------------------------------------
# the load itself
# --------------------------------------------------------------------------

def test_the_graph_holds_what_was_sent(engine):
    from etl import loader
    client, nodes, edges = engine
    assert loader.verify(client, nodes, edges) == []


def test_verification_notices_a_missing_edge(engine):
    from etl import loader
    client, nodes, edges = engine
    extra = edges + [{"_type": "TRANSITS", "src": "x", "dst": "y"}]
    assert any("TRANSITS" in m for m in loader.verify(client, nodes, extra))


def test_edges_carry_their_provenance_into_the_graph(engine):
    """A stamp that stays in Python protects nobody. It has to be queryable."""
    client, _, edges = engine
    sent = {}
    for e in edges:
        sent[e["provenance"]] = sent.get(e["provenance"], 0) + 1
    rows = client.query_readonly(
        "MATCH ()-[r]->() WITH r.provenance AS provenance, count(r) AS edges "
        "RETURN provenance, edges", "default").records
    assert dict(map(tuple, rows)) == sent


def test_no_generated_edge_reaches_a_real_organisation(engine):
    """Asked of the loaded graph, not of the lists it was built from."""
    client, _, _ = engine
    for label in ("Company", "Bank", "HoldingCompany", "LegalEntity", "Exchange",
                  "BankFailure", "Filing", "Regulator"):
        for pattern in (f"(:{label})-[r]->()", f"()-[r]->(:{label})"):
            rows = client.query_readonly(
                f'MATCH {pattern} WHERE r.provenance = "synthetic" RETURN count(r)',
                "default").records
            assert rows == [[0]], (label, pattern)
