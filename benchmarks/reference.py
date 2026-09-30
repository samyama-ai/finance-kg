"""Every catalog query, written a second time in plain Python.

Why this exists: Samyama v1.7.0 returned wrong answers without raising -- rows
in no order, joins not enforced, rows quietly dropped. A query that runs
proves nothing about whether its answer is right. So each query in
`benchmarks/queries.py` has a reference here that computes the same answer from
the node and edge lists the loader sent, with no Cypher and no engine, and
`check()` compares the two.

The references are deliberately dull: loops and dictionaries, written from the
question and not from the Cypher, so that a mistake in one is unlikely to be
repeated in the other.
"""
from __future__ import annotations

import math
from collections import defaultdict


def rounded(value: float) -> int:
    """Round half away from zero, as the engine's `round()` does.

    Python's own `round` sends 2.5 to 2.
    """
    return int(math.floor(abs(value) + 0.5)) * (1 if value >= 0 else -1)


class Graph:
    def __init__(self, nodes: list[dict], edges: list[dict]):
        self.node = {n["id"]: n for n in nodes}
        self.by_label: dict[str, list[dict]] = defaultdict(list)
        for n in nodes:
            self.by_label[n["_label"]].append(n)
        self.by_type: dict[str, list[dict]] = defaultdict(list)
        self.out: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for e in edges:
            self.by_type[e["_type"]].append(e)
            self.out[(e["_type"], e["src"])].append(e)

    def pairs(self, edge_type: str):
        """(edge, source node, target node) for every edge of a type."""
        for e in self.by_type[edge_type]:
            yield e, self.node[e["src"]], self.node[e["dst"]]

    def target(self, edge_type: str, src_id: str) -> dict:
        (found,) = self.out[(edge_type, src_id)]
        return self.node[found["dst"]]


# Each reference returns (rows, keys): every row the query could return, with
# no LIMIT applied, and beside each row the tuple it sorts on, ascending.

BILLION = 1000000000.0


def fn01(g: Graph, from_year, to_year):
    stats: dict[int, list] = defaultdict(lambda: [0, 0.0, 0.0])
    for f in g.by_label["BankFailure"]:
        if f["year"] is None or not from_year <= f["year"] <= to_year:
            continue
        entry = stats[f["year"]]
        entry[0] += 1
        entry[1] += f["assets_usd"] or 0
        entry[2] += f["estimated_loss_usd"] or 0
    rows = [[year, n, rounded(assets / BILLION), rounded(loss / BILLION)]
            for year, (n, assets, loss) in stats.items()]
    return rows, [(r[0],) for r in rows]


def fn02(g: Graph, limit):
    stats: dict[str, list] = defaultdict(lambda: [0, 0.0])
    for _, bank, holder in g.pairs("CONTROLLED_BY"):
        stats[holder["id"]][0] += 1
        stats[holder["id"]][1] += bank["assets_usd"] or 0
    # Grouped by NAME, as the query does: two holding companies that share a
    # name are one row.
    by_name: dict[str, list] = defaultdict(lambda: [0, 0.0])
    for holder_id, (n, assets) in stats.items():
        by_name[g.node[holder_id]["name"]][0] += n
        by_name[g.node[holder_id]["name"]][1] += assets
    rows = [[name, n, rounded(assets / BILLION)] for name, (n, assets) in by_name.items()]
    return rows, [(-r[1], -r[2], r[0]) for r in rows]


def fn03(g: Graph, from_year, limit):
    failures: dict[str, int] = defaultdict(int)
    for _, failure, state in g.pairs("OCCURRED_IN"):
        if failure["year"] is not None and failure["year"] >= from_year:
            failures[state["id"]] += 1
    banks: dict[str, int] = defaultdict(int)
    for _, place, state in g.pairs("LOCATED_IN"):
        if place["_label"] == "Bank":
            banks[state["id"]] += 1
    rows = [[g.node[s]["name"], n, banks[s]] for s, n in failures.items() if banks[s]]
    return rows, [(-r[1], r[0]) for r in rows]


def fn04(g: Graph, lei):
    parents: dict[str, list[str]] = defaultdict(list)
    for e in g.by_type["CONSOLIDATED_BY"]:
        parents[e["src"]].append(e["dst"])
    found: set[str] = set()
    frontier = {n["id"] for n in g.by_label["LegalEntity"] if n["lei"] == lei}
    for _ in range(6):
        frontier = {up for node_id in frontier for up in parents[node_id]}
        found |= frontier
    rows = []
    for node_id in found:
        for e in g.out[("LOCATED_IN", node_id)]:
            rows.append([g.node[node_id]["name"], g.node[e["dst"]]["name"],
                         g.node[node_id]["lei"]])
    return rows, [(r[0], r[2]) for r in rows]


def fn05(g: Graph, iso3, limit):
    home = {}
    for _, place, country in g.pairs("LOCATED_IN"):
        if place["_label"] == "LegalEntity":
            home[place["id"]] = country
    entities: dict[str, set] = defaultdict(set)
    parents: dict[str, set] = defaultdict(set)
    for e, child, parent in g.pairs("CONSOLIDATED_BY"):
        if e["level"] != "ultimate":
            continue
        here, there = home.get(child["id"]), home.get(parent["id"])
        if here is None or there is None:
            continue
        if here["iso3"] == iso3 and there["iso3"] != iso3:
            entities[there["name"]].add(child["id"])
            parents[there["name"]].add(parent["id"])
    rows = [[name, len(found), len(parents[name])] for name, found in entities.items()]
    return rows, [(-r[1], r[0]) for r in rows]


def fn06(g: Graph, limit):
    stats: dict[str, list] = defaultdict(lambda: [0, 0.0])
    for _, company, industry in g.pairs("IN_INDUSTRY"):
        if company["_label"] == "Company" and company.get("revenue_usd") is not None:
            stats[industry["name"]][0] += 1
            stats[industry["name"]][1] += company["revenue_usd"]
    rows = [[name, n, rounded(total / BILLION)] for name, (n, total) in stats.items()]
    return rows, [(-r[2], r[0]) for r in rows]


def fn07(g: Graph, limit):
    count: dict[str, int] = defaultdict(int)
    for _, company, country in g.pairs("BASED_IN"):
        if company["_label"] == "Company" and country["iso3"] != "USA":
            count[country["name"]] += 1
    rows = [[name, n] for name, n in count.items()]
    return rows, [(-r[1], r[0]) for r in rows]


def fn08(g: Graph, currency):
    rows = [[r["year"], r["date"], r["per_usd"]] for r in g.by_label["ExchangeRate"]
            if r["currency"] == currency and r["month_no"] == 12]
    return rows, [(r[0],) for r in rows]


def fn09(g: Graph, min_usd, limit):
    out: dict[str, list[dict]] = defaultdict(list)
    for e in g.by_type["TRANSFER"]:
        if e["amount_usd"] >= min_usd:
            out[e["src"]].append(e)
    rows = []
    for a, firsts in list(out.items()):
        for t1 in firsts:
            b = t1["dst"]
            for t2 in out.get(b, []):
                c = t2["dst"]
                for t3 in out.get(c, []):
                    if t3["dst"] == a and a < b and a < c:
                        rows.append([g.node[a]["account_no"], g.node[b]["account_no"],
                                     g.node[c]["account_no"], rounded(t1["amount_usd"]),
                                     rounded(t3["amount_usd"])])
    return rows, [(-r[3], r[0]) for r in rows]


def fn10(g: Graph, limit):
    rows = []
    for _, alert, account in g.pairs("FLAGS"):
        if alert["kind"] != "structuring":
            continue
        owner = g.target("OWNED_BY", account["id"])
        institution = g.target("HELD_AT", account["id"])
        rows.append([account["account_no"], owner["name"], institution["name"],
                     alert["month"], alert["transfers"], rounded(alert["amount_usd"])])
    return rows, [(-r[5], r[0]) for r in rows]


def fn11(g: Graph, min_customers, limit):
    customers: dict[str, set] = defaultdict(set)
    accounts: dict[str, set] = defaultdict(set)
    for _, account, device in g.pairs("SIGNED_IN_FROM"):
        customers[device["id"]].add(g.target("OWNED_BY", account["id"])["id"])
        accounts[device["id"]].add(account["id"])
    rows = [[d, g.node[d]["kind"], len(found), len(accounts[d])]
            for d, found in customers.items() if len(found) >= min_customers]
    return rows, [(-r[2], r[0]) for r in rows]


def fn12(g: Graph, limit):
    reason = {}
    for _, customer, entry in g.pairs("LISTED_AS"):
        reason[customer["id"]] = entry["reason"]
    owner = {e["src"]: e["dst"] for e in g.by_type["OWNED_BY"]}
    stats: dict[str, list] = defaultdict(lambda: [set(), 0, 0.0])
    for t in g.by_type["TRANSFER"]:
        listed, payer = owner[t["dst"]], owner[t["src"]]
        if listed in reason and payer != listed:
            entry = stats[listed]
            entry[0].add(payer)
            entry[1] += 1
            entry[2] += t["amount_usd"]
    rows = [[c, g.node[c]["name"], reason[c], len(payers), n, rounded(total)]
            for c, (payers, n, total) in stats.items()]
    return rows, [(-r[5], r[0]) for r in rows]


def fn13(g: Graph, limit):
    stats: dict[tuple, list] = defaultdict(lambda: [0, 0.0])
    for t, src, dst in g.pairs("TRANSFER"):
        if t["cross_border"]:
            stats[(src["iso3"], dst["iso3"])][0] += 1
            stats[(src["iso3"], dst["iso3"])][1] += t["amount_usd"]
    rows = [[a, b, n, rounded(total / 1000.0)] for (a, b), (n, total) in stats.items()]
    return rows, [(-r[3], r[0], r[1]) for r in rows]


def fn14(g: Graph, min_loans, limit):
    home = {}
    for _, who, country in g.pairs("BASED_IN"):
        if who["_label"] == "Customer":
            home[who["id"]] = country
    stats: dict[str, list] = defaultdict(lambda: [0, 0])
    for _, customer, loan in g.pairs("BORROWED"):
        country = home[customer["id"]]
        if country.get("bank_npl_pct") is None:
            continue
        stats[country["id"]][0] += 1
        stats[country["id"]][1] += loan["status"] in ("late", "defaulted")
    rows = []
    for country_id, (loans, troubled) in stats.items():
        if loans >= min_loans:
            country = g.node[country_id]
            rows.append([country["name"], loans, rounded(100.0 * troubled / loans),
                         country["bank_npl_pct"], country["bank_npl_pct_year"]])
    return rows, [(-r[2], r[0]) for r in rows]


def fn15(g: Graph, limit):
    defaulted: dict[str, set] = defaultdict(set)
    for _, customer, loan in g.pairs("BORROWED"):
        if loan["status"] == "defaulted":
            defaulted[customer["id"]].add(loan["id"])
    backers: dict[str, list[str]] = defaultdict(list)       # customer -> guarantors
    for e in g.by_type["GUARANTEES"]:
        backers[e["dst"]].append(e["src"])
    rows = []
    for borrower, loans in defaulted.items():
        found: set[str] = set()
        frontier = {borrower}
        for _ in range(3):
            frontier = {up for node_id in frontier for up in backers[node_id]}
            found |= frontier
        found.discard(borrower)
        if found:
            rows.append([borrower, g.node[borrower]["name"], len(loans), len(found)])
    return rows, [(-r[3], r[0]) for r in rows]


def fn16(g: Graph):
    count: dict[str, int] = defaultdict(int)
    for n in g.node.values():
        count[n["provenance"]] += 1
    rows = [[kind, n] for kind, n in count.items()]
    return rows, [(-r[1],) for r in rows]


REFERENCES = {
    "FN01": fn01, "FN02": fn02, "FN03": fn03, "FN04": fn04, "FN05": fn05,
    "FN06": fn06, "FN07": fn07, "FN08": fn08, "FN09": fn09, "FN10": fn10,
    "FN11": fn11, "FN12": fn12, "FN13": fn13, "FN14": fn14, "FN15": fn15,
    "FN16": fn16,
}


def same(a, b) -> bool:
    if isinstance(a, float) or isinstance(b, float):
        return (a is not None and b is not None
                and math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-6))
    return a == b


def same_row(a, b) -> bool:
    return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b, strict=True))


def check(entry: dict, got: list[list], graph: Graph, **overrides) -> list[str]:
    """What is wrong with the engine's answer. An empty list means nothing.

    Four things are checked, because the engine can fail each on its own:
    the row count, that every row is one the reference also produced, that
    the rows are in the promised order, and -- under a LIMIT -- that they are
    the TOP rows and not just any correct ones.

    Ties are allowed for: rows that sort equal may come back in either order,
    and a LIMIT may cut through a tie at either row.
    """
    params = {**entry["params"], **overrides}
    rows, keys = REFERENCES[entry["id"]](graph, **params)
    limit = params.get("limit")
    want = len(rows) if limit is None else min(limit, len(rows))
    problems = []

    if len(got) != want:
        problems.append(f"{entry['id']}: {len(got)} rows, expected {want}")

    got_keys = []
    pool = list(zip(rows, keys, strict=True))
    for row in got:
        match = next((i for i, (r, _) in enumerate(pool) if same_row(r, row)), None)
        if match is None:
            problems.append(f"{entry['id']}: row not in the reference answer: {row}")
            continue
        got_keys.append(pool.pop(match)[1])      # each reference row used once

    if got_keys != sorted(got_keys):
        problems.append(f"{entry['id']}: rows are not in the promised order")
    if sorted(got_keys) != sorted(keys)[:len(got_keys)]:
        problems.append(f"{entry['id']}: rows are correct but are not the top "
                        f"{len(got_keys)} by the sort key")
    return problems
