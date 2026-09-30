"""A tiny, MADE-UP copy of data/raw/, written in the same file formats.

The tests need the shape of the public sources, not their contents, and must
run from a clean checkout with no download. So the companies, banks and legal
entities here are invented ("Testco 3", "Test Bank 2"). Country and currency
codes are the real ones, because the code under test looks those up.

Several rows are planted to be wrong in a known way -- an exchange listed
twice, a company in a place no country matches, a relationship to an entity
that is not in the file -- so the tests can check that each is dropped or
counted.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from etl.download_data import SOURCES, WB_INDICATORS

# iso3, iso2, name, UN region, currency code
COUNTRIES = [
    ("USA", "US", "United States", "Americas", "USD"),
    ("IND", "IN", "India", "Asia", "INR"),
    ("GBR", "GB", "United Kingdom", "Europe", "GBP"),
    ("DEU", "DE", "Germany", "Europe", "EUR"),
    ("JPN", "JP", "Japan", "Asia", "JPY"),
    ("RUS", "RU", "Russia", "Europe", "RUB"),      # its rates stop early
    ("ATA", "AQ", "Antarctica", "", ""),           # no currency, no figures
]
CURRENCIES = [("USD", "US Dollar", "840"), ("INR", "Indian Rupee", "356"),
              ("GBP", "Pound Sterling", "826"), ("EUR", "Euro", "978"),
              ("JPY", "Yen", "392"), ("RUB", "Russian Ruble", "643")]
# units per euro, flat across the fixture's months
PER_EUR = {"USD": 1.10, "INR": 90.0, "GBP": 0.85, "JPY": 160.0}
MONTHS = [f"{year}-{month:02d}" for year in (2024, 2025, 2026) for month in range(1, 13)
          if (year, month) <= (2026, 8)]
STATES = [("NY", "New York"), ("CA", "California"), ("TX", "Texas")]


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def write_raw(raw_dir: Path) -> Path:
    raw_dir.mkdir(parents=True, exist_ok=True)

    def path(key: str) -> Path:
        return raw_dir / SOURCES[key]["file"]

    write_csv(path("countries"),
              ["ISO3166-1-Alpha-3", "ISO3166-1-Alpha-2", "CLDR display name",
               "official_name_en", "Region Name", "Sub-region Name",
               "ISO4217-currency_alphabetic_code"],
              [[iso3, iso2, name, name, region, "", code]
               for iso3, iso2, name, region, code in COUNTRIES])

    write_csv(path("currencies"),
              ["Entity", "Currency", "AlphabeticCode", "NumericCode", "MinorUnit",
               "WithdrawalDate"],
              [[code, name, code, numeric, 2, ""] for code, name, numeric in CURRENCIES]
              + [["OLDLAND", "Old Mark", "OLD", "000", 2, "2001-01"],   # withdrawn
                 ["NOWHERE", "No universal currency", "", "", "", ""]])

    worldbank = {code: [] for code in WB_INDICATORS}
    for n, (iso3, *_rest) in enumerate(COUNTRIES):
        if iso3 == "ATA":
            continue
        worldbank["NY.GDP.MKTP.CD"] += [
            {"iso3": iso3, "year": 2020, "value": 1.0},               # older, must lose
            {"iso3": iso3, "year": 2024, "value": 1.0e12 * (n + 1)},
        ]
        worldbank["FB.AST.NPER.ZS"].append({"iso3": iso3, "year": 2023,
                                            "value": 1.5 + n})
    path("worldbank").write_text(json.dumps(worldbank), encoding="utf-8")

    rates = [[code, month, f"{month}-28", value]
             for code, value in PER_EUR.items() for month in MONTHS]
    rates += [["RUB", "2024-01", "2024-01-31", 99.0]]                 # one month only
    rates += [["XXX", "2024-01", "2024-01-31", 5.0]]                  # unknown currency
    write_csv(path("rates"), ["currency", "month", "date", "per_eur"], rates)

    path("exchanges").write_text(json.dumps([
        {"qid": "Q1", "name": "Test Exchange New York", "mic": "XNYS", "iso3": "USA"},
        {"qid": "Q2", "name": "Test Exchange Nasdaq", "mic": "XNAS", "iso3": "USA"},
        {"qid": "Q3", "name": "Test Exchange Mumbai", "mic": "XBOM", "iso3": "IND"},
        {"qid": "Q4", "name": "Test Exchange Mumbai again", "mic": "XBOM", "iso3": "IND"},
        {"qid": "Q5", "name": "Test Exchange Nowhere", "mic": "XNOW", "iso3": None},
    ]), encoding="utf-8")

    companies, details = [], []
    for n in range(1, 13):
        exchange = ["NYSE", "Nasdaq", "OTC", None][n % 4]
        companies.append({"cik": n, "name": f"Testco {n}", "ticker": f"TC{n}",
                          "exchange": exchange})
        if n <= 8:
            details.append({
                "cik": n, "name": f"Testco {n}", "sic": f"{1000 + n % 3}",
                "sic_description": f"Test industry {n % 3}", "category": "Large filer",
                "entity_type": "operating", "fiscal_year_end": "1231",
                "incorporated_in": "Delaware", "lei": "LEI00000000000000003" if n == 3
                else None, "business_city": "Testville",
                "business_place": ["New York", "India", "Atlantis"][n % 3],
                "filings": [{"form": "10-K", "filed": f"2025-02-{n:02d}",
                             "accession": f"0000000000-25-{n:06d}",
                             "period": "2024-12-31"},
                            {"form": "10-Q", "filed": f"2025-05-{n:02d}",
                             "accession": f"0000000000-25-{100 + n:06d}",
                             "period": None}],
            })
    companies.append({"cik": 1, "name": "Testco 1", "ticker": "TC1B",
                      "exchange": "NYSE"})                  # a second share class
    path("companies").write_text(json.dumps(companies), encoding="utf-8")
    path("company_details").write_text(json.dumps(details), encoding="utf-8")
    path("company_financials").write_text(json.dumps({
        "assets_usd": [{"cik": n, "value": 1000000 * n, "end": "2024-12-31"}
                       for n in range(1, 9)],
        "revenue_usd": [{"cik": n, "value": 500000 * n, "end": "2024-12-31"}
                        for n in range(1, 6)],
        "net_income_usd": [{"cik": n, "value": -1000 * n, "end": "2024-12-31"}
                           for n in range(1, 4)],
    }), encoding="utf-8")

    banks = []
    for n in range(1, 10):
        code, state = STATES[n % 3]
        banks.append({
            "NAME": f"Test Bank {n}", "CERT": 100 + n, "CITY": "Testville",
            "STALP": code, "STNAME": state, "ASSET": 1000 * n, "DEP": 800 * n,
            "NETINC": 10 * n, "ROA": 1.1, "ROE": 9.5, "EQ": str(100 * n),
            "BKCLASS": ["N", "SM", "NM"][n % 3],
            "REGAGNT": ["OCC", "FED", "FDIC", "STATE"][n % 4],
            "ESTYMD": "01/20/1910", "NAMEHCR": f"Test Holdings {n % 4}" if n % 4 else "",
            "RSSDHCR": str(9000 + n % 4) if n % 4 else "0", "OFFDOM": n, "CB": "1",
            "SPECGRPN": "Test specialisation", "REPDTE": "06/30/2026",
        })
    path("banks").write_text(json.dumps(banks), encoding="utf-8")

    failures = [
        {"ID": str(n), "NAME": f"Failed Test Bank {n}", "CERT": 100 + n if n == 2 else None,
         "FAILDATE": f"3/{n}/2009", "FAILYR": "2009", "CITYST": f"TESTVILLE, {code}",
         "PSTALP": code, "QBFASSET": 5000 * n, "QBFDEP": 4000 * n,
         "COST": None if n == 1 else 300 * n, "RESTYPE": "FAILURE", "RESTYPE1": "PA",
         "SAVR": "DIF", "CHCLASS1": "NM"}
        for n, code in enumerate(["NY", "CA", "TX", "ZZ"], start=1)      # ZZ: no state
    ]
    path("bank_failures").write_text(json.dumps(failures), encoding="utf-8")

    entities = [
        [f"LEI{n:017d}", name, "Testpur", "IN-MH", country, country, category, "T001",
         "ACTIVE", "2015-03-01T00:00:00Z", "ISSUED"]
        for n, (name, country, category) in enumerate([
            ("TEST PARENT GROUP LIMITED", "IN", "GENERAL"),
            ("TEST SUBSIDIARY ONE PRIVATE LIMITED", "IN", "GENERAL"),
            ("TEST SUBSIDIARY TWO PRIVATE LIMITED", "IN", "GENERAL"),
            ("TEST STATE BANK", "IN", "GENERAL"),
            ("TEST FOREIGN PARENT PLC", "GB", "GENERAL"),
            ("TEST BRANCH OFFICE", "IN", "BRANCH"),
            ("TEST NOWHERE ENTITY", "ZZ", "GENERAL"),
        ], start=1)
    ]
    write_csv(path("legal_entities"),
              ["lei", "name", "city", "region", "country", "jurisdiction", "category",
               "legal_form", "status", "registered", "registration_status"], entities)
    lei = [row[0] for row in entities]
    write_csv(raw_dir / SOURCES["legal_entities"]["also"][0],
              ["child", "parent", "relationship", "since"], [
        [lei[1], lei[0], "IS_DIRECTLY_CONSOLIDATED_BY", "2016-01-01"],
        [lei[2], lei[1], "IS_DIRECTLY_CONSOLIDATED_BY", "2017-01-01"],
        [lei[0], lei[4], "IS_DIRECTLY_CONSOLIDATED_BY", "2015-01-01"],
        [lei[2], lei[4], "IS_ULTIMATELY_CONSOLIDATED_BY", "2017-01-01"],
        [lei[5], lei[4], "IS_INTERNATIONAL_BRANCH_OF", ""],
        [lei[1], "LEI99999999999999999", "IS_DIRECTLY_CONSOLIDATED_BY", ""],   # unknown
    ])
    return raw_dir
