"""Download every public source into data/raw/.

Every source here is free to download and openly licensed: public domain, CC0,
or free to reuse with the publisher cited. tests/test_docs_match_data.py refuses
any licence not on ALLOWED_LICENCES, so a source with a restriction on use
cannot be added by accident.

Nothing downloaded is committed: data/ is git-ignored.

    python -m etl.download_data                 # fetch what is missing
    python -m etl.download_data --force         # re-fetch everything
    python -m etl.download_data --only banks

Two sources are large and are reduced as they are read, so that data/raw/ holds
only what the graph uses:

  * GLEIF publishes 3.4 million legal entities in a 500 MB file. It is read
    once and the India slice is kept: see `fetch_gleif`.
  * The SEC publishes details for every filer. Details are fetched for the
    first SEC_DETAIL_LIMIT companies in its own ranked list.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import click
import requests

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RAW_DIR = DATA_DIR / "raw"
MANIFEST = "MANIFEST.json"

PUBLIC_DOMAIN = "Public domain (US government work)"
PDDL = "ODC-PDDL-1.0 (public domain)"
CC0 = "CC0 1.0 (public domain)"
CC_BY = "CC BY 4.0"
ECB_TERMS = "Free reuse, ECB cited as source"
# The only terms a source may carry. All allow any use, commercial included.
ALLOWED_LICENCES = (PUBLIC_DOMAIN, PDDL, CC0, CC_BY, ECB_TERMS)

# The SEC asks automated clients to identify themselves and to stay under ten
# requests a second. Set the SEC_USER_AGENT environment variable to your own
# organisation and contact address; no address is written into this file.
SEC_USER_AGENT = os.environ.get("SEC_USER_AGENT", "finance-kg/0.1 (+https://git.samyama.ai)")
SEC_PAUSE = 0.13
SEC_DETAIL_LIMIT = 2500
FILINGS_PER_COMPANY = 6
FILING_FORMS = ("10-K", "10-Q", "8-K", "20-F", "40-F", "6-K")
# XBRL frames: one request returns one reported figure for every filer.
# (taxonomy tag, period, property). `I` marks a point in time.
SEC_FRAMES = [
    ("Assets", "CY2024Q4I", "assets_usd"),
    ("Liabilities", "CY2024Q4I", "liabilities_usd"),
    ("StockholdersEquity", "CY2024Q4I", "equity_usd"),
    ("Revenues", "CY2024", "revenue_usd"),
    ("NetIncomeLoss", "CY2024", "net_income_usd"),
]
FRAME_YEAR = 2024

RATES_FROM = "2020-01"
GLEIF_COUNTRY = "IN"
# Sole proprietors are natural persons trading under their own name. They are
# left out: this graph holds no data about people.
GLEIF_SKIP_CATEGORIES = ("SOLE_PROPRIETOR",)
GLEIF_RELATIONSHIPS = ("IS_DIRECTLY_CONSOLIDATED_BY", "IS_ULTIMATELY_CONSOLIDATED_BY",
                       "IS_INTERNATIONAL_BRANCH_OF")
GLEIF_FIELDS = {
    "LEI": "lei",
    "Entity.LegalName": "name",
    "Entity.LegalAddress.City": "city",
    "Entity.LegalAddress.Region": "region",
    "Entity.LegalAddress.Country": "country",
    "Entity.LegalJurisdiction": "jurisdiction",
    "Entity.EntityCategory": "category",
    "Entity.LegalForm.EntityLegalFormCode": "legal_form",
    "Entity.EntityStatus": "status",
    "Registration.InitialRegistrationDate": "registered",
    "Registration.RegistrationStatus": "registration_status",
}

# World Bank indicator code -> the Country property it becomes.
WB_INDICATORS = {
    "NY.GDP.MKTP.CD": "gdp_usd",
    "FP.CPI.TOTL.ZG": "inflation_pct",
    "FR.INR.LEND": "lending_rate_pct",
    "FS.AST.PRVT.GD.ZS": "private_credit_pct_gdp",
    "FB.AST.NPER.ZS": "bank_npl_pct",
    "FB.BNK.CAPA.ZS": "bank_capital_to_assets_pct",
    "CM.MKT.LCAP.GD.ZS": "market_cap_pct_gdp",
    "FX.OWN.TOTL.ZS": "account_ownership_pct",
}

FDIC_BANK_FIELDS = ("NAME,CERT,CITY,STALP,STNAME,ASSET,DEP,NETINC,ROA,ROE,EQ,BKCLASS,"
                    "REGAGNT,ESTYMD,NAMEHCR,RSSDHCR,OFFDOM,CB,SPECGRPN,REPDTE")
FDIC_FAILURE_FIELDS = ("NAME,CERT,FAILDATE,FAILYR,CITYST,PSTALP,QBFASSET,QBFDEP,COST,"
                       "RESTYPE,RESTYPE1,SAVR,CHCLASS1")

EXCHANGES_SPARQL = """
SELECT ?item ?itemLabel ?mic ?iso3 WHERE {
  ?item wdt:P7534 ?mic .
  OPTIONAL { ?item wdt:P17 ?country . ?country wdt:P298 ?iso3 }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
"""

# key -> what it is, where it comes from, and the terms it is offered under.
# tests/test_docs_match_data.py pins this table to docs/data-provenance.md.
SOURCES: dict[str, dict] = {
    "countries": {
        "title": "ISO 3166 country codes",
        "publisher": "Open Knowledge / datasets",
        "url": "https://raw.githubusercontent.com/datasets/country-codes/main/data/country-codes.csv",
        "page": "https://github.com/datasets/country-codes",
        "licence": PDDL, "citation": "datasets/country-codes",
        "file": "countries.csv", "kind": "http",
    },
    "currencies": {
        "title": "ISO 4217 currency codes",
        "publisher": "Open Knowledge / datasets",
        "url": "https://raw.githubusercontent.com/datasets/currency-codes/main/data/codes-all.csv",
        "page": "https://github.com/datasets/currency-codes",
        "licence": PDDL, "citation": "datasets/currency-codes",
        "file": "currencies.csv", "kind": "http",
    },
    "worldbank": {
        "title": "Country financial indicators",
        "publisher": "World Bank",
        "url": "https://api.worldbank.org/v2/country/all/indicator",
        "page": "https://data.worldbank.org/indicator/FS.AST.PRVT.GD.ZS",
        "licence": CC_BY,
        "citation": "Source: World Bank, World Development Indicators",
        "file": "worldbank.json", "kind": "worldbank",
    },
    "rates": {
        "title": "Euro foreign exchange reference rates",
        "publisher": "European Central Bank",
        "url": "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip",
        "page": "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html",
        "licence": ECB_TERMS, "citation": "Source: European Central Bank",
        "file": "rates.csv", "kind": "ecb",
    },
    "exchanges": {
        "title": "Stock exchanges and trading venues with a market code",
        "publisher": "Wikidata",
        "url": "https://query.wikidata.org/sparql",
        "page": "https://www.wikidata.org",
        "licence": CC0, "citation": "Wikidata",
        "file": "exchanges.json", "kind": "wikidata",
    },
    "companies": {
        "title": "Companies that file with the SEC, their tickers and exchanges",
        "publisher": "US Securities and Exchange Commission",
        "url": "https://www.sec.gov/files/company_tickers_exchange.json",
        "page": "https://www.sec.gov/search-filings/edgar-application-programming-interfaces",
        "licence": PUBLIC_DOMAIN, "citation": "Source: US Securities and Exchange Commission",
        "file": "companies.json", "kind": "sec_tickers",
    },
    "company_details": {
        "title": "Company profiles and recent filings",
        "publisher": "US Securities and Exchange Commission",
        "url": "https://data.sec.gov/submissions",
        "page": "https://www.sec.gov/search-filings/edgar-application-programming-interfaces",
        "licence": PUBLIC_DOMAIN, "citation": "Source: US Securities and Exchange Commission",
        "file": "company_details.json", "kind": "sec_details",
    },
    "company_financials": {
        "title": "Reported financial figures, fiscal 2024",
        "publisher": "US Securities and Exchange Commission",
        "url": "https://data.sec.gov/api/xbrl/frames/us-gaap",
        "page": "https://www.sec.gov/search-filings/edgar-application-programming-interfaces",
        "licence": PUBLIC_DOMAIN, "citation": "Source: US Securities and Exchange Commission",
        "file": "company_financials.json", "kind": "sec_frames",
    },
    "banks": {
        "title": "Active FDIC-insured banks",
        "publisher": "US Federal Deposit Insurance Corporation",
        "url": "https://banks.data.fdic.gov/api/institutions",
        "page": "https://banks.data.fdic.gov/bankfind-suite/bulkData",
        "licence": PUBLIC_DOMAIN,
        "citation": "Source: Federal Deposit Insurance Corporation",
        "file": "banks.json", "kind": "fdic_banks",
    },
    "bank_failures": {
        "title": "Bank failures since 1934",
        "publisher": "US Federal Deposit Insurance Corporation",
        "url": "https://banks.data.fdic.gov/api/failures",
        "page": "https://banks.data.fdic.gov/bankfind-suite/bulkData",
        "licence": PUBLIC_DOMAIN,
        "citation": "Source: Federal Deposit Insurance Corporation",
        "file": "bank_failures.json", "kind": "fdic_failures",
    },
    "legal_entities": {
        "title": "Legal entities in India and their parent companies",
        "publisher": "GLEIF",
        "url": "https://goldencopy.gleif.org/api/v2/golden-copies/publishes/latest",
        "page": "https://www.gleif.org/en/lei-data/gleif-golden-copy",
        "licence": CC0, "citation": "GLEIF",
        "file": "legal_entities.csv", "kind": "gleif",
        "also": ["legal_entity_relationships.csv"],
    },
}

SESSION = requests.Session()
SESSION.headers["User-Agent"] = "finance-kg/0.1 (+https://git.samyama.ai)"


def get(url: str, params: dict | None = None, headers: dict | None = None,
        tries: int = 4) -> requests.Response:
    """GET with backoff."""
    last: Exception | None = None
    for attempt in range(tries):
        try:
            resp = SESSION.get(url, params=params, headers=headers, timeout=180)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"giving up on {url}: {last}")


def sec_get(url: str) -> requests.Response:
    time.sleep(SEC_PAUSE)
    return get(url, headers={"User-Agent": SEC_USER_AGENT})


def fetch_http(src: dict, out: Path) -> int:
    out.write_bytes(get(src["url"]).content)
    with out.open(encoding="utf-8-sig", newline="") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def fetch_worldbank(src: dict, out: Path) -> int:
    """One file holding every indicator, keeping only observed values."""
    collected: dict[str, list[dict]] = {}
    for code in WB_INDICATORS:
        payload = get(f"{src['url']}/{code}",
                      {"format": "json", "per_page": 20000, "date": "2010:2030"}).json()
        meta, rows = payload[0], payload[1] or []
        if meta.get("pages", 1) != 1:
            raise RuntimeError(f"{code}: {meta['pages']} pages, expected one")
        collected[code] = [
            {"iso3": r["countryiso3code"], "year": int(r["date"]), "value": r["value"]}
            for r in rows if r["value"] is not None and r["countryiso3code"]
        ]
    out.write_text(json.dumps(collected), encoding="utf-8")
    return sum(len(v) for v in collected.values())


def fetch_ecb(src: dict, out: Path) -> int:
    """The last published rate of each month, per currency, against the euro.

    The ECB asks that any change to its figures be stated. None is made: each
    value kept is a rate the ECB published, on the date recorded beside it.
    """
    archive = zipfile.ZipFile(io.BytesIO(get(src["url"]).content))
    with archive.open(archive.namelist()[0]) as handle:
        rows = list(csv.reader(io.TextIOWrapper(handle, encoding="utf-8")))
    header = [c.strip() for c in rows[0]]
    last: dict[tuple[str, str], tuple[str, str]] = {}
    for row in rows[1:]:
        day = row[0]
        if day[:7] < RATES_FROM:
            continue
        for code, value in zip(header[1:], row[1:], strict=False):
            if not code or value.strip() in ("", "N/A"):
                continue
            key = (code, day[:7])
            if key not in last or day > last[key][0]:
                last[key] = (day, value.strip())
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["currency", "month", "date", "per_eur"])
        for (code, month), (day, value) in sorted(last.items()):
            writer.writerow([code, month, day, value])
    return len(last)


def fetch_wikidata(src: dict, out: Path) -> int:
    payload = get(src["url"], {"query": EXCHANGES_SPARQL, "format": "json"},
                  headers={"Accept": "application/sparql-results+json",
                           "User-Agent": SESSION.headers["User-Agent"]}).json()
    rows = [
        {"qid": b["item"]["value"].rsplit("/", 1)[1], "name": b["itemLabel"]["value"],
         "mic": b["mic"]["value"], "iso3": b.get("iso3", {}).get("value")}
        for b in payload["results"]["bindings"]
    ]
    rows.sort(key=lambda r: (r["mic"], r["qid"], r["iso3"] or ""))
    out.write_text(json.dumps(rows), encoding="utf-8")
    return len(rows)


def fetch_sec_tickers(src: dict, out: Path) -> int:
    payload = sec_get(src["url"]).json()
    rows = [dict(zip(payload["fields"], row, strict=True)) for row in payload["data"]]
    out.write_text(json.dumps(rows), encoding="utf-8")
    return len(rows)


def ranked_ciks(raw_dir: Path) -> list[int]:
    """CIKs in the order the SEC lists them, each once."""
    rows = json.loads((raw_dir / SOURCES["companies"]["file"]).read_text(encoding="utf-8"))
    seen: dict[int, None] = {}
    for row in rows:
        seen.setdefault(row["cik"], None)
    return list(seen)


def fetch_sec_details(src: dict, out: Path) -> int:
    """Profile and recent filings of the first SEC_DETAIL_LIMIT companies."""
    details = []
    for cik in ranked_ciks(out.parent)[:SEC_DETAIL_LIMIT]:
        payload = sec_get(f"{src['url']}/CIK{cik:010d}.json").json()
        recent = payload.get("filings", {}).get("recent", {})
        filings = []
        for form, filed, accession, period in zip(
                recent.get("form", []), recent.get("filingDate", []),
                recent.get("accessionNumber", []), recent.get("reportDate", []),
                strict=False):
            if form in FILING_FORMS and len(filings) < FILINGS_PER_COMPANY:
                filings.append({"form": form, "filed": filed, "accession": accession,
                                "period": period or None})
        business = (payload.get("addresses") or {}).get("business") or {}
        details.append({
            "cik": cik, "name": payload.get("name"),
            "sic": payload.get("sic") or None,
            "sic_description": payload.get("sicDescription") or None,
            "category": payload.get("category") or None,
            "entity_type": payload.get("entityType") or None,
            "fiscal_year_end": payload.get("fiscalYearEnd") or None,
            "incorporated_in": payload.get("stateOfIncorporationDescription") or None,
            "lei": payload.get("lei") or None,
            "business_city": business.get("city") or None,
            "business_place": business.get("stateOrCountryDescription") or None,
            "filings": filings,
        })
    out.write_text(json.dumps(details), encoding="utf-8")
    return len(details)


def fetch_sec_frames(src: dict, out: Path) -> int:
    collected: dict[str, list[dict]] = {}
    for tag, period, prop in SEC_FRAMES:
        payload = sec_get(f"{src['url']}/{tag}/USD/{period}.json").json()
        collected[prop] = [{"cik": r["cik"], "value": r["val"], "end": r["end"]}
                           for r in payload["data"]]
    out.write_text(json.dumps(collected), encoding="utf-8")
    return sum(len(v) for v in collected.values())


def fetch_fdic(url: str, fields: str, filters: str | None, out: Path) -> int:
    rows, offset = [], 0
    while True:
        params = {"fields": fields, "limit": 10000, "offset": offset, "format": "json"}
        if filters:
            params["filters"] = filters
        payload = get(url, params).json()
        page = [item["data"] for item in payload["data"]]
        rows += page
        offset += len(page)
        if not page or offset >= payload["meta"]["total"]:
            break
    if len(rows) != payload["meta"]["total"]:
        raise RuntimeError(f"{url}: service reports {payload['meta']['total']} rows, "
                           f"fetched {len(rows)}")
    # The service is paged without a sort key, so a row could in principle be
    # served twice and another missed. The row count alone would not show it.
    if len({row["ID"] for row in rows}) != len(rows):
        raise RuntimeError(f"{url}: paging returned the same row more than once")
    out.write_text(json.dumps(rows), encoding="utf-8")
    return len(rows)


def fetch_fdic_banks(src: dict, out: Path) -> int:
    return fetch_fdic(src["url"], FDIC_BANK_FIELDS, "ACTIVE:1", out)


def fetch_fdic_failures(src: dict, out: Path) -> int:
    return fetch_fdic(src["url"], FDIC_FAILURE_FIELDS, None, out)


def download_to(url: str, path: Path) -> None:
    with SESSION.get(url, stream=True, timeout=600) as resp:
        resp.raise_for_status()
        with path.open("wb") as handle:
            for block in resp.iter_content(1 << 20):
                handle.write(block)


def zipped_rows(path: Path):
    """Header and rows of the one CSV inside a zip, read as a stream."""
    archive = zipfile.ZipFile(path)
    handle = archive.open(archive.namelist()[0])
    reader = csv.reader(io.TextIOWrapper(handle, encoding="utf-8"))
    return next(reader), reader


def fetch_gleif(src: dict, out: Path) -> int:
    """The India slice of GLEIF: about 20,000 of 3.4 million entities.

    Kept are (1) every entity in India that is a parent or a subsidiary of
    another, (2) the parents and subsidiaries of those, wherever they are, and
    (3) every entity in India with BANK in its name. Sole proprietors are left
    out throughout. The two large files are deleted once read.
    """
    latest = get(src["url"]).json()["data"]
    files = {kind: latest[kind]["full_file"]["csv"]["url"] for kind in ("lei2", "rr")}
    with tempfile.TemporaryDirectory() as tmp:
        entities_zip, relations_zip = Path(tmp) / "lei2.zip", Path(tmp) / "rr.zip"
        download_to(files["rr"], relations_zip)
        download_to(files["lei2"], entities_zip)

        header, rows = zipped_rows(relations_zip)
        at = {name: i for i, name in enumerate(header)}
        relations = [
            (r[at["Relationship.StartNode.NodeID"]], r[at["Relationship.EndNode.NodeID"]],
             r[at["Relationship.RelationshipType"]],
             r[at["Relationship.Period.1.startDate"]][:10])
            for r in rows
            if r[at["Relationship.RelationshipStatus"]] == "ACTIVE"
            and r[at["Relationship.RelationshipType"]] in GLEIF_RELATIONSHIPS
        ]

        header, rows = zipped_rows(entities_zip)
        at = {name: i for i, name in enumerate(header)}
        columns = [at[name] for name in GLEIF_FIELDS]
        country_at, category_at = at["Entity.LegalAddress.Country"], at["Entity.EntityCategory"]
        name_at = at["Entity.LegalName"]
        every: dict[str, list[str]] = {}
        in_country: set[str] = set()
        banks: set[str] = set()
        for r in rows:
            if r[category_at] in GLEIF_SKIP_CATEGORIES:
                continue
            every[r[0]] = [r[c] for c in columns]
            if r[country_at] == GLEIF_COUNTRY:
                in_country.add(r[0])
                if "BANK" in r[name_at].upper():
                    banks.add(r[0])

    kept_relations = sorted(
        rel for rel in relations
        if rel[0] in every and rel[1] in every
        and (rel[0] in in_country or rel[1] in in_country)
    )
    kept = banks | {lei for rel in kept_relations for lei in rel[:2]}
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(list(GLEIF_FIELDS.values()))
        writer.writerows(every[lei] for lei in sorted(kept))
    with (out.parent / src["also"][0]).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["child", "parent", "relationship", "since"])
        writer.writerows(kept_relations)
    return len(kept)


FETCHERS = {
    "http": fetch_http,
    "worldbank": fetch_worldbank,
    "ecb": fetch_ecb,
    "wikidata": fetch_wikidata,
    "sec_tickers": fetch_sec_tickers,
    "sec_details": fetch_sec_details,
    "sec_frames": fetch_sec_frames,
    "fdic_banks": fetch_fdic_banks,
    "fdic_failures": fetch_fdic_failures,
    "gleif": fetch_gleif,
}


def files_of(src: dict) -> list[str]:
    return [src["file"], *src.get("also", [])]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_manifest(raw_dir: Path = RAW_DIR) -> dict:
    path = raw_dir / MANIFEST
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def missing(raw_dir: Path = RAW_DIR) -> list[str]:
    """Sources with a file that is not in `raw_dir`."""
    return [key for key, src in SOURCES.items()
            if not all((raw_dir / name).exists() for name in files_of(src))]


def strays(raw_dir: Path = RAW_DIR) -> list[str]:
    """Files in `raw_dir` that no current source accounts for."""
    if not raw_dir.exists():
        return []
    known = {name for src in SOURCES.values() for name in files_of(src)} | {MANIFEST}
    return sorted(p.name for p in raw_dir.iterdir() if p.is_file() and p.name not in known)


def download_all(only: tuple[str, ...] = (), force: bool = False,
                 raw_dir: Path = RAW_DIR) -> dict:
    raw_dir.mkdir(parents=True, exist_ok=True)
    manifest = {k: v for k, v in read_manifest(raw_dir).items() if k in SOURCES}
    for key, src in SOURCES.items():
        if only and key not in only:
            continue
        out = raw_dir / src["file"]
        if key not in missing(raw_dir) and not force:
            print(f"[skip]     {key:20} {out.name} already present")
            continue
        started = time.time()
        rows = FETCHERS[src["kind"]](src, out)
        manifest[key] = {
            "files": files_of(src), "url": src["url"], "licence": src["licence"],
            "citation": src["citation"], "rows": rows,
            "bytes": sum((raw_dir / name).stat().st_size for name in files_of(src)),
            "sha256": {name: sha256(raw_dir / name) for name in files_of(src)},
            "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        print(f"[download] {key:20} {rows:>8,} rows  "
              f"{manifest[key]['bytes'] / 1024:>9,.0f} KB  {time.time() - started:6.1f}s")
        (raw_dir / MANIFEST).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


@click.command()
@click.option("--only", multiple=True, type=click.Choice(sorted(SOURCES)),
              help="Fetch just this source. Repeatable.")
@click.option("--force", is_flag=True, help="Re-fetch files that are already present.")
@click.option("--prune", is_flag=True,
              help="Delete files in data/raw/ that no current source accounts for.")
def main(only, force, prune):
    download_all(only, force)
    left = strays()
    if left and prune:
        for name in left:
            (RAW_DIR / name).unlink()
            print(f"[prune]    removed {name}")
    elif left:
        print(f"\n{len(left)} file(s) in {RAW_DIR} belong to no current source: "
              f"{', '.join(left)}. Remove them with --prune.")
    gone = missing()
    if gone:
        raise SystemExit(f"still missing: {', '.join(gone)}")
    print(f"\nall {len(SOURCES)} sources present in {RAW_DIR}")
    print("next:  python -m etl.loader --dry-run")


if __name__ == "__main__":
    main()
