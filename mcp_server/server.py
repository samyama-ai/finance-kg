"""MCP server exposing the finance KG.

    python -m mcp_server.server                       # embedded, quick subset
    python -m mcp_server.server --scale 1.0           # embedded, full graph
    FINANCE_KG_URL=http://127.0.0.1:8080 python -m mcp_server.server
    python -m mcp_server.server --list-tools

Each tool is one entry from `benchmarks/queries.py`, so the queries an agent can
run are exactly the ones that are checked against a reference answer. Adding a
tool means adding a catalog entry and its reference, not writing fresh Cypher
here where nothing would check it.

Every answer carries its `layer` and a plain statement of what that means. An
agent reading "accounts flagged for structuring" must be able to tell, without
being told, that the accounts and their owners are invented.
"""
from __future__ import annotations

import argparse
import os
import sys

from fastmcp import FastMCP

from benchmarks.queries import QUERIES, get, render
from etl import generate as gen
from etl import loader

URL_ENV = "FINANCE_KG_URL"
GRAPH_ENV = "FINANCE_KG_GRAPH"
# The embedded engine loads at start-up. The real layer is always loaded in
# full; this scales the generated one.
DEFAULT_SCALE = 0.2

LAYER_NOTE = {
    "real": ("Public data only, from the SEC, the FDIC, GLEIF, the ECB, the World "
             "Bank and Wikidata. This is a statement about the world."),
    "synthetic": ("GENERATED data only. Customers, institutions, accounts, payments, "
                  "loans, watchlist entries and alerts are invented, with coined "
                  "names. No real person, company or bank is among them. This shows "
                  "the question being answered; the numbers describe nothing real."),
    "both": ("GENERATED activity measured against REAL reference data, such as an "
             "invented payment priced at a real exchange rate. The reference figure "
             "is real; the activity is invented."),
}

mcp = FastMCP("finance-kg")
_client = None
_settings = {"url": os.environ.get(URL_ENV), "scale": DEFAULT_SCALE,
             "seed": gen.DEFAULT_SEED,
             "graph": os.environ.get(GRAPH_ENV, loader.GRAPH)}


def graph_name() -> str:
    """The graph to query. The embedded engine always uses the default one."""
    return _settings["graph"] if _settings["url"] else loader.GRAPH


def client():
    """Connect on first use, so `--list-tools` needs no engine and no data."""
    global _client
    if _client is None:
        if _settings["url"]:
            _client = loader.connect(_settings["url"])
        else:
            _client, _, _ = loader.load_embedded(
                "all", _settings["seed"], _settings["scale"],
                log=lambda msg: print(msg, file=sys.stderr))
    return _client


def answer(query_id: str, **params) -> dict:
    entry = get(query_id)
    given = {k: v for k, v in params.items() if v is not None}
    result = client().query(render(entry, **given), graph_name())
    return {
        "id": entry["id"],
        "question": entry["question"],
        "parameters": {**entry["params"], **given},
        "columns": result.columns,
        "rows": result.records,
        "layer": entry["layer"],
        "how_to_read_this": LAYER_NOTE[entry["layer"]],
    }


@mcp.tool()
def list_questions() -> list[dict]:
    """Every question this graph can answer, and what each answer rests on."""
    return [{"id": q["id"], "title": q["title"], "question": q["question"],
             "layer": q["layer"], "parameters": q["params"],
             "why_graph": q["why_graph"]} for q in QUERIES]


@mcp.tool()
def bank_failures_by_year(from_year: int = 2007, to_year: int = 2026) -> dict:
    """US bank failures per year, with assets and cost to the insurance fund.
    Real data."""
    return answer("FN01", from_year=from_year, to_year=to_year)


@mcp.tool()
def largest_bank_holding_companies(limit: int = 10) -> dict:
    """Holding companies that control the most US banks. Real data."""
    return answer("FN02", limit=limit)


@mcp.tool()
def bank_failures_by_state(from_year: int = 2008, limit: int = 10) -> dict:
    """States that lost the most banks, and how many operate there now.
    Real data."""
    return answer("FN03", from_year=from_year, limit=limit)


@mcp.tool()
def parents_of_legal_entity(lei: str) -> dict:
    """Every parent above a legal entity, by its 20-character LEI. Real data.
    Covers entities in India and their parents."""
    return answer("FN04", lei=lei.upper())


@mcp.tool()
def countries_owning_companies_in(iso3: str = "IND", limit: int = 10) -> dict:
    """Foreign countries whose entities ultimately own the most legal entities
    in a country. Real data. Only India is covered in depth."""
    return answer("FN05", iso3=iso3.upper(), limit=limit)


@mcp.tool()
def industries_by_revenue(limit: int = 10) -> dict:
    """Industries ranked by revenue reported to the SEC. Real data."""
    return answer("FN06", limit=limit)


@mcp.tool()
def foreign_companies_listed_in_us(limit: int = 10) -> dict:
    """Countries, other than the US, home to the most SEC filers. Real data."""
    return answer("FN07", limit=limit)


@mcp.tool()
def currency_against_dollar(currency: str = "INR") -> dict:
    """A currency's year-end rate against the US dollar, by ISO 4217 code.
    Real data."""
    return answer("FN08", currency=currency.upper())


@mcp.tool()
def payment_rings(min_usd: float = 15000.0, limit: int = 10) -> dict:
    """Sets of three accounts that passed a large sum round in a circle."""
    return answer("FN09", min_usd=float(min_usd), limit=limit)


@mcp.tool()
def structuring_alerts(limit: int = 10) -> dict:
    """Accounts flagged for repeated payments just under the reporting
    threshold, with their owners and institutions."""
    return answer("FN10", limit=limit)


@mcp.tool()
def shared_devices(min_customers: int = 3, limit: int = 10) -> dict:
    """Devices used to sign in to the accounts of several customers."""
    return answer("FN11", min_customers=min_customers, limit=limit)


@mcp.tool()
def watchlist_exposure(limit: int = 10) -> dict:
    """For each customer on the watchlist, who paid them and how much."""
    return answer("FN12", limit=limit)


@mcp.tool()
def payment_corridors(limit: int = 10) -> dict:
    """Country pairs with the most cross-border payments, in dollars at the
    real exchange rate of each payment's month."""
    return answer("FN13", limit=limit)


@mcp.tool()
def troubled_loans_by_country(min_loans: int = 20, limit: int = 10) -> dict:
    """Share of loans late or in default per country, beside the World Bank's
    national bad-loan ratio."""
    return answer("FN14", min_loans=min_loans, limit=limit)


@mcp.tool()
def guarantors_of_defaulted_borrowers(limit: int = 10) -> dict:
    """Borrowers in default and the customers who guarantee them, directly or
    through a chain."""
    return answer("FN15", limit=limit)


@mcp.tool()
def provenance_split() -> dict:
    """How much of this graph is real and how much is generated."""
    return answer("FN16")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="finance-kg-mcp")
    parser.add_argument("--url", default=os.environ.get(URL_ENV),
                        help=f"A running Samyama server. Also read from ${URL_ENV}.")
    parser.add_argument("--graph", default=os.environ.get(GRAPH_ENV, loader.GRAPH),
                        help=f"Graph, or tenant, on the server. Also ${GRAPH_ENV}.")
    parser.add_argument("--scale", type=float, default=DEFAULT_SCALE,
                        help="Size of the generated layer in embedded mode.")
    parser.add_argument("--seed", type=int, default=gen.DEFAULT_SEED)
    parser.add_argument("--list-tools", action="store_true",
                        help="Print the tools and exit. Needs no engine.")
    args = parser.parse_args(argv)
    _settings.update(url=args.url, scale=args.scale, seed=args.seed, graph=args.graph)

    if args.list_tools:
        import asyncio
        tools = asyncio.run(mcp.list_tools())
        print(f"finance-kg: {len(tools)} tools\n")
        for tool in tools:
            first_line = (tool.description or "").strip().splitlines()[0]
            print(f"  {tool.name:40} {first_line}")
        return

    client()            # load before serving, so the first call is not the slow one
    mcp.run()


if __name__ == "__main__":
    main()
