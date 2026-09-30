"""The real layer: everything that comes from a public source.

Reads data/raw/ (written by etl/download_data.py) and returns nodes and edges.
Every node and edge built here is stamped `provenance: real`, and every node
carries the URL of the dataset it came from. Nothing in this file invents a
value: a field the source leaves blank stays absent from the graph.

What the real layer holds: countries and their financial indicators,
currencies and exchange rates, stock exchanges, US-listed companies with their
filings and reported figures, US banks with their holding companies and
failures, and legal entities in India with their parent companies.

What it does not hold: accounts, payments, loans to customers, or anything
about a named person. None of that is public. It is generated, separately, in
etl/generate.py, and never attached to a company or bank named here.

Rows that cannot be joined are DROPPED AND COUNTED, never patched.
"""
from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from etl.download_data import FRAME_YEAR, RAW_DIR, SOURCES, WB_INDICATORS
from etl.helpers import REAL, edge, node, to_float, to_int

# The SEC names an exchange in words; Wikidata identifies it by market code.
# These four pairs are matched by hand. An SEC name with no pair here leaves
# the company without a LISTED_ON edge, and is counted.
SEC_EXCHANGE_MIC = {"NYSE": "XNYS", "Nasdaq": "XNAS", "CBOE": "XCBO", "OTC": "OTCM"}

# How the SEC writes three places that the country file spells differently.
PLACE_ALIASES = {"united kingdom": "GBR", "korea republic of": "KOR",
                 "virgin islands british": "VGB"}

# FDIC's code for a bank's primary federal regulator, and the agency it names.
REGULATORS = {
    "FDIC": "Federal Deposit Insurance Corporation",
    "OCC": "Office of the Comptroller of the Currency",
    "FED": "Federal Reserve System",
}
# FDIC reports money in thousands of dollars. It is stored in dollars.
FDIC_UNIT = 1000
USA = "country:USA"


def src_url(key: str) -> str:
    return SOURCES[key]["page"]


def read_json(raw_dir: Path, name: str):
    return json.loads((raw_dir / name).read_text(encoding="utf-8"))


def read_csv(raw_dir: Path, name: str) -> list[dict]:
    with (raw_dir / name).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def us_date(text: str | None) -> str | None:
    """FDIC writes `7/17/2026`. The graph stores ISO 8601."""
    if not text:
        return None
    return datetime.strptime(text, "%m/%d/%Y").strftime("%Y-%m-%d")


def dollars(value) -> int | None:
    number = to_float(value)
    return None if number is None else int(round(number * FDIC_UNIT))


def plain(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


# --------------------------------------------------------------------------
# reference data
# --------------------------------------------------------------------------

def latest_indicators(worldbank: dict) -> dict[str, dict]:
    """iso3 -> {property: value, property_year: year}, the newest value of each.

    The year is stored beside every value because the indicators stop in
    different years, and a figure with no year invites comparison with one
    from a different decade.
    """
    out: dict[str, dict] = defaultdict(dict)
    for code, prop in WB_INDICATORS.items():
        newest: dict[str, dict] = {}
        for row in worldbank.get(code, []):
            seen = newest.get(row["iso3"])
            if seen is None or row["year"] > seen["year"]:
                newest[row["iso3"]] = row
        for iso3, row in newest.items():
            value = row["value"]
            out[iso3][prop] = int(round(value)) if prop == "gdp_usd" else round(value, 3)
            out[iso3][f"{prop}_year"] = row["year"]
    return out


def build_countries(raw_dir: Path):
    """Countries, and the currencies each one uses."""
    indicators = latest_indicators(read_json(raw_dir, SOURCES["worldbank"]["file"]))
    nodes, lookup, uses = [], {"iso2": {}, "name": {}}, []
    for row in read_csv(raw_dir, SOURCES["countries"]["file"]):
        iso3 = row["ISO3166-1-Alpha-3"]
        if not iso3:
            continue
        node_id = f"country:{iso3}"
        name = row["CLDR display name"] or row["official_name_en"] or iso3
        lookup["iso2"][row["ISO3166-1-Alpha-2"]] = node_id
        for known in (name, row["official_name_en"], row.get("UNTERM English Short"),
                      row.get("UNTERM English Formal")):
            if known:
                lookup["name"][plain(known.split("(", 1)[0])] = node_id
        nodes.append(node(
            "Country", node_id, REAL, src_url("countries"),
            iso3=iso3, iso2=row["ISO3166-1-Alpha-2"] or None, name=name,
            official_name=row["official_name_en"] or None,
            region=row["Region Name"] or None, sub_region=row["Sub-region Name"] or None,
            **indicators.get(iso3, {}),
        ))
        for code in (row.get("ISO4217-currency_alphabetic_code") or "").split(","):
            if code.strip():
                uses.append((node_id, code.strip()))
    # Names the SEC uses that no column of the country file spells the same way.
    for alias, iso3 in PLACE_ALIASES.items():
        lookup["name"][alias] = f"country:{iso3}"
    return nodes, lookup, uses


def build_currencies(raw_dir: Path, uses: list[tuple[str, str]], report: dict):
    """One node per current currency code. Withdrawn codes are left out."""
    names: dict[str, dict] = {}
    for row in read_csv(raw_dir, SOURCES["currencies"]["file"]):
        code = row["AlphabeticCode"]
        if not code or row["WithdrawalDate"]:
            continue
        names.setdefault(code, row)
    nodes = [
        node("Currency", f"currency:{code}", REAL, src_url("currencies"),
             code=code, name=row["Currency"], numeric_code=row["NumericCode"] or None,
             minor_unit=to_int(row["MinorUnit"]))
        for code, row in sorted(names.items())
    ]
    edges = []
    for country_id, code in uses:
        if code not in names:
            report["country_currencies_dropped_unknown_code"] += 1
            continue
        edges.append(edge("USES", country_id, f"currency:{code}", REAL))
    return nodes, edges


def build_rates(raw_dir: Path, currencies: set[str], report: dict):
    """Month-end exchange rates.

    `per_eur` is the rate the ECB published. `per_usd` is DERIVED from it, by
    dividing by the dollar's own rate on the same date, and is marked so in
    docs/data-provenance.md as the ECB's terms require.

    The ECB quotes every currency against the euro, so it publishes no row for
    the euro itself. One is added per month, with `per_eur` of 1, so that an
    amount in euros can be converted like any other.
    """
    rows = read_csv(raw_dir, SOURCES["rates"]["file"])
    dollar = {r["month"]: float(r["per_eur"]) for r in rows if r["currency"] == "USD"}
    dates = {r["month"]: r["date"] for r in rows if r["currency"] == "USD"}
    rows = rows + [{"currency": "EUR", "month": month, "date": dates[month],
                    "per_eur": "1"} for month in sorted(dollar)]
    nodes, edges = [], []
    for row in rows:
        currency_id = f"currency:{row['currency']}"
        if currency_id not in currencies:
            report["rates_dropped_unknown_currency"] += 1
            continue
        if row["month"] not in dollar:
            report["rates_dropped_no_dollar_rate"] += 1
            continue
        per_eur = float(row["per_eur"])
        node_id = f"rate:{row['currency']}:{row['month']}"
        nodes.append(node(
            "ExchangeRate", node_id, REAL, src_url("rates"),
            currency=row["currency"], month=row["month"], date=row["date"],
            year=int(row["month"][:4]), month_no=int(row["month"][5:]), per_eur=per_eur,
            per_usd=round(per_eur / dollar[row["month"]], 6),
        ))
        edges.append(edge("RATE_OF", node_id, currency_id, REAL))
    return nodes, edges


def build_exchanges(raw_dir: Path, countries: set[str], report: dict):
    """One node per market code. Wikidata lists some venues more than once."""
    nodes, edges, seen = [], [], set()
    for row in read_json(raw_dir, SOURCES["exchanges"]["file"]):
        if row["mic"] in seen:
            report["exchanges_dropped_listed_twice"] += 1
            continue
        seen.add(row["mic"])
        node_id = f"exchange:{row['mic']}"
        nodes.append(node("Exchange", node_id, REAL,
                          f"https://www.wikidata.org/wiki/{row['qid']}",
                          mic=row["mic"], name=row["name"], wikidata_id=row["qid"],
                          iso3=row["iso3"]))
        if row["iso3"] and f"country:{row['iso3']}" in countries:
            edges.append(edge("LOCATED_IN", node_id, f"country:{row['iso3']}", REAL))
        else:
            report["exchanges_with_no_known_country"] += 1
    return nodes, edges


# --------------------------------------------------------------------------
# companies
# --------------------------------------------------------------------------

def place_to_country(place: str, state_codes: set, state_names: set, lookup: dict):
    """The country behind an SEC place description, or None.

    A US state comes as a code ("CA") or a name; another country as a name,
    sometimes behind a province ("Ontario, Canada") or a note ("Canada
    (Federal Level)").
    """
    text = plain(place)
    if text in state_codes or text in state_names:
        return USA
    candidates = [text, plain(place.rsplit(",", 1)[-1]), plain(place.split("(", 1)[0])]
    if "," in place:                           # "Korea, Republic of"
        tail, head = place.split(",", 1)
        candidates.append(plain(f"{head} {tail}"))
    for candidate in candidates:
        if candidate in lookup["name"]:
            return lookup["name"][candidate]
    return None


def build_companies(raw_dir: Path, lookup: dict, states: dict[str, str],
                    exchanges: set[str], report: dict):
    listings: dict[int, list[dict]] = defaultdict(list)
    for row in read_json(raw_dir, SOURCES["companies"]["file"]):
        listings[row["cik"]].append(row)
    details = {d["cik"]: d
               for d in read_json(raw_dir, SOURCES["company_details"]["file"])}
    figures: dict[int, dict] = defaultdict(dict)
    for prop, rows in read_json(raw_dir, SOURCES["company_financials"]["file"]).items():
        for row in rows:
            figures[row["cik"]][prop] = int(row["value"])
            figures[row["cik"]].setdefault("fiscal_period_end", row["end"])

    # The SEC gives a US state as its two-letter code and any other place as
    # a name, sometimes with a province in front: "Ontario, Canada".
    state_codes = {code.lower() for code in states}
    state_names = {plain(name) for name in states.values()}
    nodes, edges, industries = [], [], {}
    filings_seen: set[str] = set()
    for cik, rows in listings.items():
        detail = details.get(cik, {})
        node_id = f"company:{cik}"
        reported = figures.get(cik, {})
        nodes.append(node(
            "Company", node_id, REAL, src_url("companies"),
            cik=cik, name=rows[0]["name"], ticker=rows[0]["ticker"],
            tickers=", ".join(sorted({r["ticker"] for r in rows})),
            category=detail.get("category"), entity_type=detail.get("entity_type"),
            fiscal_year_end=detail.get("fiscal_year_end"),
            incorporated_in=detail.get("incorporated_in"),
            city=detail.get("business_city"), lei=detail.get("lei"),
            fiscal_year=FRAME_YEAR if reported else None, **reported,
        ))
        for mic in sorted({SEC_EXCHANGE_MIC.get(r["exchange"]) for r in rows} - {None}):
            if f"exchange:{mic}" in exchanges:
                ticker = next(r["ticker"] for r in rows
                              if SEC_EXCHANGE_MIC.get(r["exchange"]) == mic)
                edges.append(edge("LISTED_ON", node_id, f"exchange:{mic}", REAL,
                                  ticker=ticker))
            else:
                report["listings_dropped_exchange_not_in_data"] += 1
        if not any(r["exchange"] for r in rows):
            report["companies_with_no_exchange_named"] += 1

        if detail.get("sic"):
            industry_id = f"industry:{detail['sic']}"
            industries[industry_id] = detail.get("sic_description") or detail["sic"]
            edges.append(edge("IN_INDUSTRY", node_id, industry_id, REAL))

        place = detail.get("business_place") or ""
        if place:
            country_id = place_to_country(place, state_codes, state_names, lookup)
            if country_id:
                edges.append(edge("BASED_IN", node_id, country_id, REAL))
            else:
                report["companies_with_unrecognised_place"] += 1

        for filing in detail.get("filings", []):
            filing_id = f"filing:{filing['accession']}"
            if filing_id in filings_seen:
                # A filing made jointly by two registrants is listed under
                # each. It is one document, and belongs to the first filer.
                report["filings_dropped_listed_twice"] += 1
                continue
            filings_seen.add(filing_id)
            nodes.append(node("Filing", filing_id, REAL, src_url("company_details"),
                              accession=filing["accession"], form=filing["form"],
                              filed=filing["filed"], period=filing["period"],
                              year=int(filing["filed"][:4])))
            edges.append(edge("FILED_BY", filing_id, node_id, REAL))

    industry_nodes = [
        node("Industry", industry_id, REAL, src_url("company_details"),
             sic=industry_id.split(":")[1], name=name)
        for industry_id, name in sorted(industries.items())
    ]
    return industry_nodes + nodes, edges


# --------------------------------------------------------------------------
# banks
# --------------------------------------------------------------------------

def build_states(raw_dir: Path) -> tuple[list[dict], list[dict], dict[str, str]]:
    names = {}
    for row in read_json(raw_dir, SOURCES["banks"]["file"]):
        if row.get("STALP") and row.get("STNAME"):
            names[row["STALP"]] = row["STNAME"]
    nodes = [node("State", f"state:{code}", REAL, src_url("banks"), code=code, name=name)
             for code, name in sorted(names.items())]
    edges = [edge("PART_OF", n["id"], USA, REAL) for n in nodes]
    return nodes, edges, names


def build_banks(raw_dir: Path, states: dict[str, str], report: dict):
    nodes, edges, holders = [], [], {}
    regulators = [node("Regulator", f"regulator:{code}", REAL, src_url("banks"),
                       code=code, name=name) for code, name in REGULATORS.items()]
    active = set()
    for row in read_json(raw_dir, SOURCES["banks"]["file"]):
        node_id = f"bank:{row['CERT']}"
        active.add(row["CERT"])
        nodes.append(node(
            "Bank", node_id, REAL, src_url("banks"),
            cert=row["CERT"], name=row["NAME"], city=row.get("CITY"),
            state=row.get("STALP"), charter_class=row.get("BKCLASS"),
            specialisation=row.get("SPECGRPN") or None,
            community_bank=str(row.get("CB")) == "1",
            established=us_date(row.get("ESTYMD")), offices=to_int(row.get("OFFDOM")),
            assets_usd=dollars(row.get("ASSET")), deposits_usd=dollars(row.get("DEP")),
            equity_usd=dollars(row.get("EQ")), net_income_usd=dollars(row.get("NETINC")),
            return_on_assets_pct=to_float(row.get("ROA")),
            return_on_equity_pct=to_float(row.get("ROE")),
            reported=us_date(row.get("REPDTE")),
        ))
        if row.get("STALP") in states:
            edges.append(edge("LOCATED_IN", node_id, f"state:{row['STALP']}", REAL))
        else:
            report["banks_with_no_known_state"] += 1
        if row.get("REGAGNT") in REGULATORS:
            edges.append(edge("SUPERVISED_BY", node_id, f"regulator:{row['REGAGNT']}", REAL))
        else:
            report["banks_with_no_federal_regulator_named"] += 1
        holder = str(row.get("RSSDHCR") or "").strip()
        if holder and holder != "0" and row.get("NAMEHCR"):
            holders[holder] = row["NAMEHCR"]
            edges.append(edge("CONTROLLED_BY", node_id, f"holding:{holder}", REAL))
    holding = [node("HoldingCompany", f"holding:{rssd}", REAL, src_url("banks"),
                    rssd_id=rssd, name=name) for rssd, name in sorted(holders.items())]
    return regulators + holding + nodes, edges, active


def build_failures(raw_dir: Path, states: dict[str, str], active: set, report: dict):
    nodes, edges = [], []
    for number, row in enumerate(read_json(raw_dir, SOURCES["bank_failures"]["file"]), 1):
        node_id = f"failure:{row.get('ID') or number}"
        city = (row.get("CITYST") or "").rsplit(",", 1)[0].strip().title() or None
        nodes.append(node(
            "BankFailure", node_id, REAL, src_url("bank_failures"),
            name=row["NAME"], cert=row.get("CERT"), city=city, state=row.get("PSTALP"),
            failed=us_date(row.get("FAILDATE")), year=to_int(row.get("FAILYR")),
            resolution=row.get("RESTYPE"), resolution_type=row.get("RESTYPE1"),
            insurance_fund=row.get("SAVR"), charter_class=row.get("CHCLASS1"),
            assets_usd=dollars(row.get("QBFASSET")),
            deposits_usd=dollars(row.get("QBFDEP")),
            estimated_loss_usd=dollars(row.get("COST")),
        ))
        if row.get("PSTALP") in states:
            edges.append(edge("OCCURRED_IN", node_id, f"state:{row['PSTALP']}", REAL))
        else:
            report["failures_with_no_known_state"] += 1
        if row.get("CERT") in active:
            edges.append(edge("FAILURE_OF", node_id, f"bank:{row['CERT']}", REAL))
    return nodes, edges


# --------------------------------------------------------------------------
# legal entities
# --------------------------------------------------------------------------

RELATIONSHIP_EDGE = {
    "IS_DIRECTLY_CONSOLIDATED_BY": ("CONSOLIDATED_BY", "direct"),
    "IS_ULTIMATELY_CONSOLIDATED_BY": ("CONSOLIDATED_BY", "ultimate"),
    "IS_INTERNATIONAL_BRANCH_OF": ("BRANCH_OF", None),
}


def build_legal_entities(raw_dir: Path, lookup: dict, report: dict):
    source = SOURCES["legal_entities"]
    nodes, edges, known = [], [], set()
    for row in read_csv(raw_dir, source["file"]):
        node_id = f"lei:{row['lei']}"
        known.add(node_id)
        nodes.append(node(
            "LegalEntity", node_id, REAL, src_url("legal_entities"),
            lei=row["lei"], name=row["name"], city=row["city"] or None,
            region=row["region"] or None, country=row["country"] or None,
            jurisdiction=row["jurisdiction"] or None, category=row["category"] or None,
            legal_form=row["legal_form"] or None, status=row["status"] or None,
            registration_status=row["registration_status"] or None,
            registered=(row["registered"] or "")[:10] or None,
            is_bank="BANK" in row["name"].upper(),
        ))
        country_id = lookup["iso2"].get(row["country"])
        if country_id:
            edges.append(edge("LOCATED_IN", node_id, country_id, REAL))
        else:
            report["legal_entities_with_no_known_country"] += 1
    for row in read_csv(raw_dir, source["also"][0]):
        child, parent = f"lei:{row['child']}", f"lei:{row['parent']}"
        if child not in known or parent not in known:
            report["relationships_dropped_unknown_entity"] += 1
            continue
        kind, level = RELATIONSHIP_EDGE[row["relationship"]]
        edges.append(edge(kind, child, parent, REAL, level=level,
                          since=row["since"] or None))
    return nodes, edges, known


def link_companies(nodes: list[dict], entities: set[str]) -> list[dict]:
    """A company and a legal entity with the same LEI are the same organisation."""
    return [edge("SAME_AS", n["id"], f"lei:{n['lei']}", REAL)
            for n in nodes
            if n["_label"] == "Company" and n.get("lei") and f"lei:{n['lei']}" in entities]


# --------------------------------------------------------------------------

def build(raw_dir: Path = RAW_DIR):
    """Returns (nodes, edges, dropped)."""
    report: dict[str, int] = defaultdict(int)

    countries, lookup, uses = build_countries(raw_dir)
    country_ids = {n["id"] for n in countries}
    currencies, currency_edges = build_currencies(raw_dir, uses, report)
    rates, rate_edges = build_rates(raw_dir, {n["id"] for n in currencies}, report)
    exchanges, exchange_edges = build_exchanges(raw_dir, country_ids, report)

    states, state_edges, state_names = build_states(raw_dir)
    companies, company_edges = build_companies(
        raw_dir, lookup, state_names, {n["id"] for n in exchanges}, report)
    banks, bank_edges, active = build_banks(raw_dir, state_names, report)
    failures, failure_edges = build_failures(raw_dir, state_names, active, report)
    entities, entity_edges, entity_ids = build_legal_entities(raw_dir, lookup, report)

    nodes = (countries + currencies + rates + exchanges + states + companies
             + banks + failures + entities)
    edges = (currency_edges + rate_edges + exchange_edges + state_edges
             + company_edges + bank_edges + failure_edges + entity_edges
             + link_companies(companies, entity_ids))
    return nodes, edges, dict(report)
