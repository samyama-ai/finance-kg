"""The build and the pre-load checks -- the half that needs no engine.

Two failures are worth guarding above all. A dangling edge endpoint: the engine
skips such an edge in silence and the load reports success. And a generated
fact attached to a real organisation: an invented account at a real bank is an
invented claim about it.
"""
from __future__ import annotations

import copy
import json
from collections import Counter

import pytest

from etl import loader
from etl.generate import (
    STRUCTURING_FLOOR_USD,
    STRUCTURING_MINIMUM,
    THRESHOLD_USD,
    World,
    structuring_hits,
)
from etl.helpers import REAL, SYNTHETIC, cypher_literal, edge, node, props_map


def by_label(nodes, label):
    return [n for n in nodes if n["_label"] == label]


def by_type(edges, edge_type):
    return [e for e in edges if e["_type"] == edge_type]


# --------------------------------------------------------------------------
# the real layer
# --------------------------------------------------------------------------

def test_real_layer_is_internally_consistent(real_graph):
    nodes, edges, _ = real_graph
    assert loader.check_integrity(nodes, edges) == []
    assert {n["provenance"] for n in nodes} == {REAL}
    assert {e["provenance"] for e in edges} == {REAL}
    assert {n["_label"] for n in nodes} == set(loader.REAL_LABELS)


def test_the_real_layer_holds_no_banking_activity(real_graph):
    """No accounts, payments or loans to customers: none of it is public, so
    none may appear stamped real."""
    nodes, edges, _ = real_graph
    assert not {n["_label"] for n in nodes} & set(loader.SYNTHETIC_LABELS)
    assert not {e["_type"] for e in edges} & {"TRANSFER", "OWNED_BY", "HELD_AT",
                                              "BORROWED", "LISTED_AS", "FLAGS"}


def test_unjoinable_rows_are_dropped_and_counted(real_graph):
    """The fixture plants bad rows of each kind. Each must be left out or
    counted, so a join that starts shrinking is seen."""
    _, _, dropped = real_graph
    assert dropped == {
        "rates_dropped_unknown_currency": 1,
        "exchanges_dropped_listed_twice": 1,
        "exchanges_with_no_known_country": 1,
        "listings_dropped_exchange_not_in_data": 3,
        "companies_with_no_exchange_named": 3,
        "companies_with_unrecognised_place": 3,
        "banks_with_no_federal_regulator_named": 2,
        "failures_with_no_known_state": 1,
        "legal_entities_with_no_known_country": 1,
        "relationships_dropped_unknown_entity": 1,
    }


def test_the_newest_indicator_value_wins_and_keeps_its_year(real_graph):
    nodes, _, _ = real_graph
    india = next(n for n in nodes if n["id"] == "country:IND")
    assert india["gdp_usd"] == 2 * 10**12 and india["gdp_usd_year"] == 2024


def test_a_country_with_no_figure_has_no_property(real_graph):
    """Absent, not zero: a zero would rank Antarctica as the poorest economy."""
    nodes, _, _ = real_graph
    assert "gdp_usd" not in next(n for n in nodes if n["id"] == "country:ATA")


def test_withdrawn_currencies_are_left_out(real_graph):
    nodes, _, _ = real_graph
    codes = {n["code"] for n in by_label(nodes, "Currency")}
    assert codes == {"USD", "INR", "GBP", "EUR", "JPY", "RUB"}


def test_dollar_rates_are_derived_from_the_published_euro_rates(real_graph):
    nodes, _, _ = real_graph
    rate = {(n["currency"], n["month"]): n for n in by_label(nodes, "ExchangeRate")}
    rupee = rate[("INR", "2025-06")]
    assert rupee["per_eur"] == 90.0
    assert rupee["per_usd"] == pytest.approx(90.0 / 1.10, abs=1e-6)
    assert rate[("USD", "2025-06")]["per_usd"] == 1.0
    assert rate[("EUR", "2025-06")]["per_eur"] == 1.0
    assert rate[("EUR", "2025-06")]["per_usd"] == pytest.approx(1 / 1.10, abs=1e-6)
    assert rupee["year"] == 2025 and rupee["month_no"] == 6


def test_fdic_money_is_stored_in_dollars_not_thousands(real_graph):
    nodes, _, _ = real_graph
    bank = next(n for n in nodes if n["id"] == "bank:103")
    assert bank["assets_usd"] == 3000 * 1000 and bank["deposits_usd"] == 2400 * 1000
    assert bank["established"] == "1910-01-20"


def test_a_failure_with_no_loss_recorded_has_no_loss_property(real_graph):
    nodes, _, _ = real_graph
    first = next(n for n in nodes if n["id"] == "failure:1")
    assert "estimated_loss_usd" not in {k for k, v in first.items() if v is not None}
    assert first["failed"] == "2009-03-01" and first["city"] == "Testville"


def test_a_bank_with_no_holding_company_has_no_control_edge(real_graph):
    nodes, edges, _ = real_graph
    controlled = {e["src"] for e in by_type(edges, "CONTROLLED_BY")}
    assert len(by_label(nodes, "Bank")) - len(controlled) == 2       # banks 4 and 8
    assert "holding:0" not in {n["id"] for n in nodes}


def test_a_company_in_a_us_state_is_based_in_the_us(real_graph):
    _, edges, _ = real_graph
    based = {e["src"]: e["dst"] for e in by_type(edges, "BASED_IN")}
    assert based["company:3"] == "country:USA"          # "New York"
    assert based["company:1"] == "country:IND"          # "India"
    assert "company:2" not in based                     # "Atlantis"


def test_a_company_with_two_share_classes_is_one_company(real_graph):
    nodes, _, _ = real_graph
    first = [n for n in by_label(nodes, "Company") if n["cik"] == 1]
    assert len(first) == 1 and first[0]["tickers"] == "TC1, TC1B"


def test_only_reported_figures_are_stored(real_graph):
    nodes, _, _ = real_graph
    company = {n["cik"]: n for n in by_label(nodes, "Company")}
    assert company[2]["net_income_usd"] == -2000          # a loss is a value
    assert company[7].get("revenue_usd") is None
    assert company[10].get("assets_usd") is None and company[10].get("fiscal_year") is None


def test_a_company_is_linked_to_its_legal_entity_by_lei(real_graph):
    _, edges, _ = real_graph
    assert [(e["src"], e["dst"]) for e in by_type(edges, "SAME_AS")] == [
        ("company:3", "lei:LEI00000000000000003")]


def test_ownership_keeps_its_level(real_graph):
    _, edges, _ = real_graph
    levels = Counter(e["level"] for e in by_type(edges, "CONSOLIDATED_BY"))
    assert levels == {"direct": 3, "ultimate": 1}
    assert len(by_type(edges, "BRANCH_OF")) == 1


# --------------------------------------------------------------------------
# the generated layer
# --------------------------------------------------------------------------

def test_full_graph_is_internally_consistent(full_graph):
    nodes, edges, _ = full_graph
    assert loader.check_integrity(nodes, edges) == []
    assert {n["_label"] for n in nodes} == set(loader.NODE_LABELS)


def test_generation_is_deterministic(raw_dir, full_graph):
    nodes, edges, _ = full_graph
    again_nodes, again_edges, _ = loader.build("all", seed=20260929, scale=0.05,
                                               raw_dir=raw_dir)
    assert json.dumps([nodes, edges], sort_keys=True) == json.dumps(
        [again_nodes, again_edges], sort_keys=True)


def test_a_different_seed_gives_a_different_graph(raw_dir, full_graph):
    nodes, _, _ = full_graph
    other, _, _ = loader.build("all", seed=1, scale=0.05, raw_dir=raw_dir)
    names = [n["name"] for n in by_label(nodes, "Customer")]
    assert names != [n["name"] for n in by_label(other, "Customer")]


def test_the_generator_leaves_the_real_layer_untouched(real_graph, full_graph):
    real_nodes, real_edges, _ = real_graph
    nodes, edges, _ = full_graph
    assert nodes[:len(real_nodes)] == real_nodes
    assert edges[:len(real_edges)] == real_edges


def test_everything_generated_is_stamped_synthetic(real_graph, full_graph):
    nodes, edges, _ = full_graph
    assert {n["provenance"] for n in nodes[len(real_graph[0]):]} == {SYNTHETIC}
    assert {e["provenance"] for e in edges[len(real_graph[1]):]} == {SYNTHETIC}


def test_nothing_generated_touches_a_real_organisation(full_graph):
    """The rule this graph rests on. Generated edges may reach a real country,
    currency or industry, and nothing else real."""
    nodes, edges, _ = full_graph
    node_of = {n["id"]: n for n in nodes}
    reached = Counter()
    for e in edges:
        if e["provenance"] == SYNTHETIC:
            for end in (e["src"], e["dst"]):
                if node_of[end]["provenance"] == REAL:
                    reached[node_of[end]["_label"]] += 1
    assert set(reached) <= loader.NEUTRAL_LABELS
    assert reached["Country"] and reached["Currency"] and reached["Industry"]


def test_no_generated_name_is_the_name_of_something_real(full_graph):
    nodes, _, _ = full_graph
    real = {n["name"].lower() for n in nodes
            if n["provenance"] == REAL and isinstance(n.get("name"), str)}
    for n in nodes:
        if n["provenance"] == SYNTHETIC and isinstance(n.get("name"), str):
            assert n["name"].lower() not in real, n["name"]


def test_a_currency_with_gaps_in_its_rates_is_not_used(real_graph, full_graph):
    """The fixture's rouble has one month of rates. A payment in roubles would
    have no dollar value in any other month."""
    world = World(*real_graph[:2])
    assert "RUS" not in world.currency_of
    _, edges, _ = full_graph
    assert "RUB" not in {e["currency"] for e in by_type(edges, "TRANSFER")}


def test_every_transfer_is_priced_at_the_real_rate(full_graph):
    nodes, edges, _ = full_graph
    rate = {(n["currency"], n["month"]): n["per_usd"]
            for n in by_label(nodes, "ExchangeRate")}
    transfers = by_type(edges, "TRANSFER")
    assert len({t["currency"] for t in transfers}) >= 4
    for t in transfers:
        assert t["month"] == t["date"][:7]
        assert t["amount_usd"] == pytest.approx(
            t["amount"] / rate[(t["currency"], t["month"])], abs=0.011)


def test_every_pattern_is_planted(full_graph):
    _, edges, _ = full_graph
    patterns = Counter(t["pattern"] for t in by_type(edges, "TRANSFER"))
    assert set(patterns) == {"background", "ring", "structuring", "mule"}
    assert patterns["background"] > 10 * patterns["ring"]


def test_a_ring_comes_back_to_where_it_started(full_graph):
    _, edges, _ = full_graph
    ring = [t for t in by_type(edges, "TRANSFER") if t["pattern"] == "ring"]
    sends, receives = Counter(t["src"] for t in ring), Counter(t["dst"] for t in ring)
    assert sends == receives and set(sends.values()) == {1}


def test_alerts_are_raised_by_the_rule_not_by_the_planting(full_graph):
    """Each alert is exactly one (account, month) where the rule fires, and
    its figures are the sum of the transfers that fired it."""
    nodes, edges, _ = full_graph
    hits = structuring_hits([{**t, "src": t["src"], "dst": t["dst"]}
                             for t in by_type(edges, "TRANSFER")])
    node_of = {n["id"]: n for n in nodes}
    flagged = {}
    for e in by_type(edges, "FLAGS"):
        alert = node_of[e["src"]]
        flagged[(e["dst"], alert["month"])] = alert
    assert set(flagged) == set(hits) and flagged
    for key, alert in flagged.items():
        assert alert["transfers"] == len(hits[key]) >= STRUCTURING_MINIMUM
        assert alert["amount_usd"] == pytest.approx(
            sum(t["amount_usd"] for t in hits[key]), abs=0.01)
        for t in hits[key]:
            assert STRUCTURING_FLOOR_USD <= t["amount_usd"] < THRESHOLD_USD


def test_a_shared_device_means_something(full_graph):
    """An account signs in from its own customer's device. Only planted rings
    and mules share one across customers."""
    nodes, edges, _ = full_graph
    owner = {e["src"]: e["dst"] for e in by_type(edges, "OWNED_BY")}
    planted = {a for t in by_type(edges, "TRANSFER") if t["pattern"] in ("ring", "mule")
               for a in (t["src"], t["dst"])}
    customers, accounts = {}, {}
    for e in by_type(edges, "SIGNED_IN_FROM"):
        customers.setdefault(e["dst"], set()).add(owner[e["src"]])
        accounts.setdefault(e["dst"], set()).add(e["src"])
    shared = [d for d, found in customers.items() if len(found) > 1]
    assert shared
    for device in shared:
        assert accounts[device] <= planted, device


def test_watchlist_entries_name_generated_customers_only(full_graph):
    nodes, edges, _ = full_graph
    node_of = {n["id"]: n for n in nodes}
    listed = by_type(edges, "LISTED_AS")
    assert listed
    for e in listed:
        assert node_of[e["src"]]["_label"] == "Customer"
        assert node_of[e["src"]]["name"] == node_of[e["dst"]]["name"]
    assert {n["list_name"] for n in by_label(nodes, "WatchlistEntry")} == {
        "Scenario watchlist"}


# --------------------------------------------------------------------------
# the integrity checks themselves
# --------------------------------------------------------------------------

def test_a_dangling_endpoint_is_caught(real_graph):
    nodes, edges, _ = real_graph
    broken = edges + [edge("LOCATED_IN", "bank:101", "state:NOPE", REAL)]
    assert any("state:NOPE" in p for p in loader.check_integrity(nodes, broken))


def test_a_duplicate_id_is_caught(real_graph):
    nodes, edges, _ = real_graph
    assert any("duplicate id" in p
               for p in loader.check_integrity(nodes + [nodes[0]], edges))


def test_a_generated_node_passing_as_real_is_caught(full_graph):
    nodes, edges, _ = full_graph
    forged = copy.deepcopy(nodes)
    next(n for n in forged if n["_label"] == "Customer")["provenance"] = REAL
    assert any("invariant 1" in p for p in loader.check_integrity(forged, edges))


def test_a_real_stamp_on_a_generated_edge_is_caught(full_graph):
    nodes, edges, _ = full_graph
    customer = by_label(nodes, "Customer")[0]
    forged = edges + [edge("BASED_IN", customer["id"], "country:IND", REAL)]
    assert any("invariant 2" in p for p in loader.check_integrity(nodes, forged))


@pytest.mark.parametrize("edge_type, target", [
    ("HELD_AT", "bank:101"),
    ("HELD_AT", "holding:9001"),
    ("OWNED_BY", "company:1"),
    ("OWNED_BY", "lei:LEI00000000000000001"),
])
def test_an_account_at_a_real_organisation_is_caught(full_graph, edge_type, target):
    """An invented account at a real bank, or owned by a real company."""
    nodes, edges, _ = full_graph
    account = by_label(nodes, "Account")[0]
    forged = edges + [edge(edge_type, account["id"], target, SYNTHETIC)]
    assert any("invariant 3" in p and target in p
               for p in loader.check_integrity(nodes, forged))


def test_a_real_company_on_the_watchlist_is_caught(full_graph):
    nodes, edges, _ = full_graph
    entry = by_label(nodes, "WatchlistEntry")[0]
    forged = edges + [edge("LISTED_AS", "company:1", entry["id"], SYNTHETIC)]
    assert any("invariant 3" in p for p in loader.check_integrity(nodes, forged))


def test_an_account_with_no_owner_is_caught(full_graph):
    nodes, edges, _ = full_graph
    account = by_label(nodes, "Account")[0]
    cut = [e for e in edges
           if not (e["_type"] == "OWNED_BY" and e["src"] == account["id"])]
    assert any("invariant 4" in p and account["id"] in p
               for p in loader.check_integrity(nodes, cut))


def test_a_transfer_priced_at_the_wrong_rate_is_caught(full_graph):
    nodes, edges, _ = full_graph
    forged = copy.deepcopy(edges)
    next(e for e in forged if e["_type"] == "TRANSFER")["amount_usd"] += 5.0
    assert any("invariant 5" in p for p in loader.check_integrity(nodes, forged))


def test_missing_data_is_refused_not_loaded_partially(tmp_path):
    with pytest.raises(loader.MissingData, match="download_data"):
        loader.build("real", raw_dir=tmp_path)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def test_string_literals_are_double_quoted_and_escaped():
    assert cypher_literal("plain") == '"plain"'
    assert cypher_literal('has "quotes"') == '"has \\"quotes\\""'
    assert cypher_literal("Macy's") == '"Macy\'s"'
    assert cypher_literal(None) == "null"
    assert cypher_literal(True) == "true"


def test_null_properties_are_dropped_not_written():
    out = props_map({"_label": "X", "id": "a:1", "year": None, "rate": 3.5})
    assert "year" not in out and "_label" not in out
    assert 'id: "a:1"' in out and "rate: 3.5" in out


def test_nothing_can_be_made_without_provenance():
    with pytest.raises(ValueError):
        node("Bank", "bank:1", "guessed", "https://example.org")
    with pytest.raises(ValueError):
        node("Bank", "bank:1", REAL, "generated")
    with pytest.raises(ValueError):
        node("Customer", "customer:1", SYNTHETIC, "https://example.org")
    with pytest.raises(TypeError):
        edge("HELD_AT", "account:1", "institution:1")
    with pytest.raises(ValueError):
        edge("HELD_AT", "account:1", "institution:1", "guessed")


def test_dry_run_writes_every_node_and_edge(full_graph, tmp_path):
    nodes, edges, _ = full_graph
    out = loader.write_cypher(nodes, edges, tmp_path / "load.cypher")
    text = out.read_text(encoding="utf-8")
    assert text.count("\nCREATE (:") == len(nodes)
    assert text.count("\nMATCH (a:") == len(edges)
