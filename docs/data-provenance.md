# Data provenance

Where every part of this graph comes from, what terms it is offered under, and
what is invented.

## The short version

| Layer | Nodes | Edges | What it is |
|---|---:|---:|---|
| Real | 56,043 | 83,041 | Organisations and reference data, from public sources free of restrictions on use |
| Generated | 13,394 | 66,346 | Banking activity, invented from a seed and kept apart from every real organisation |

Every node and every edge carries `provenance` (`real` or `synthetic`), so the
split is a query and not only a claim in this document:

```cypher
MATCH (n) WITH n.provenance AS provenance, count(n) AS nodes
RETURN provenance, nodes ORDER BY nodes DESC
```

**Nothing downloaded is committed to this repository.** `data/` is git-ignored.

## Terms of use

Every source is public domain, CC0, CC BY 4.0, or free to reuse with the
publisher cited. All allow any use, including commercial use and public
display. Three obligations follow:

> Credit the World Bank wherever its figures are shown:
> *Source: World Bank, World Development Indicators.*

> Cite the ECB wherever its exchange rates are shown: *Source: European Central
> Bank.* The ECB also asks that any change to its figures be stated; the one
> change made is described under `rates` below.

> The SEC asks for a citation as a courtesy, not a condition:
> *Source: US Securities and Exchange Commission.*

This is a reading of each publisher's stated terms, made on 2026-09-29. It is
not legal advice.

A test refuses any source whose licence is not on the allowed list.

## Sources

Keys match `SOURCES` in `etl/download_data.py`. A test pins this table to that
code, so a source cannot be added to one and left out of the other.

| Key | What it supplies | Publisher | Terms |
|---|---|---|---|
| `countries` | 249 countries: codes, names, regions, currency codes | Open Knowledge `datasets/country-codes` | ODC-PDDL 1.0, public domain |
| `currencies` | ISO 4217 currency codes and names | Open Knowledge `datasets/currency-codes` | ODC-PDDL 1.0, public domain |
| `worldbank` | GDP, inflation, lending rate, private credit, bank bad-loan ratio, bank capital ratio, market capitalisation, account ownership | World Bank, World Development Indicators | CC BY 4.0 |
| `rates` | Month-end euro reference rates for 31 current currencies, January 2020 onwards | European Central Bank | Free reuse, ECB cited as source |
| `exchanges` | 1,931 stock exchanges and trading venues with an ISO 10383 market code | Wikidata | CC0 1.0, public domain |
| `companies` | 8,004 companies that file with the SEC, with tickers and exchanges | US Securities and Exchange Commission | Public domain (US government work) |
| `company_details` | Industry, place, filer category and recent filings for the first 2,500 companies in the SEC's list | US Securities and Exchange Commission | Public domain (US government work) |
| `company_financials` | Assets, liabilities, equity, revenue and net income for fiscal 2024, as reported in XBRL | US Securities and Exchange Commission | Public domain (US government work) |
| `banks` | 4,231 active FDIC-insured banks: assets, deposits, income, regulator, holding company | US Federal Deposit Insurance Corporation | Public domain (US government work) |
| `bank_failures` | 4,117 bank failures since 1934 | US Federal Deposit Insurance Corporation | Public domain (US government work) |
| `legal_entities` | 16,934 legal entities: those in India that are parents or subsidiaries, their parents anywhere, and every entity in India with BANK in its name | GLEIF | CC0 1.0, public domain |

`data/raw/MANIFEST.json` records, for each file, the URL it came from, when it
was fetched, its size and its SHA-256.

### How the large sources are reduced

- **GLEIF** publishes 3.4 million entities in a 500 MB file. The download reads
  it once and keeps the India slice described above. Sole proprietors, who are
  natural persons trading under their own name, are left out throughout. The
  large files are deleted after reading.
- **SEC company profiles** are one request per company, and the SEC allows ten
  a second. Profiles are fetched for the first 2,500 companies in the SEC's own
  list, which is ordered by market size. The other 5,504 companies have a name,
  ticker and exchange, and no profile.
- **SEC financial figures** come from the XBRL "frames" API, which returns one
  figure for every filer in one request. Five figures are fetched for fiscal
  2024. Companies that report under IFRS rather than US GAAP, which includes
  most foreign filers, are not in these frames and have no figures.

## Where the real data is thin

| Limit | Detail |
|---|---|
| **India has entities, not figures** | GLEIF gives an Indian entity's name, legal form, address and parents, and nothing financial. The only Indian companies with reported figures are the few that file with the SEC. |
| **Banks are US only** | FDIC covers US banks. Indian banks appear only as GLEIF legal entities, found by the word BANK in their name, which also catches a few that are not banks. |
| **Companies are US-listed only** | The SEC covers companies listed in the US, including foreign ones such as Infosys and HDFC Bank. Wikidata's lists of NSE and BSE companies were too thin to use. |
| **Filings are a sample** | Six recent filings of the main kinds per profiled company, not the full history. |
| **Rates are month-end only** | One rate per currency per month, the last the ECB published that month. Ten currencies the ECB no longer quotes, such as the rouble, stop in the month they stopped. |
| **`per_usd` is derived** | The ECB quotes against the euro. `per_usd` is `per_eur` divided by the dollar's own `per_eur` on the same date, and a euro row with `per_eur` of 1 is added per month. This is the one change made to ECB figures, stated here as the ECB's terms require. |
| **Money units** | FDIC reports in thousands of dollars; the graph stores dollars. SEC figures are as reported, in dollars. |
| **Regulator names** | FDIC gives a regulator as a code (`FDIC`, `OCC`, `FED`). The agency name beside each code is written into the loader, not read from the data. |
| **Exchange names** | The SEC names a company's exchange in words and Wikidata by market code. The four pairs (`NYSE`/XNYS, `Nasdaq`/XNAS, `CBOE`/XCBO, `OTC`/OTCM) are matched by hand. |

## What is left out, and counted

Rows that cannot be joined are dropped and reported by the loader on every run.
They are never patched.

| Reason | Count | |
|---|---:|---|
| `rates_dropped_unknown_currency` | 108 | Rates for currencies that ISO 4217 has withdrawn, such as the Croatian kuna |
| `exchanges_with_no_known_country` | 74 | Wikidata gives the venue no country |
| `exchanges_dropped_listed_twice` | 29 | Wikidata lists the same market code more than once; the first is kept |
| `companies_with_no_exchange_named` | 146 | The SEC list names no exchange for the company |
| `filings_dropped_listed_twice` | 7 | A filing made jointly by two registrants is listed under each; it is kept under the first |
| `banks_with_no_federal_regulator_named` | 2 | The regulator code is `STATE`, which names no federal agency |
| `companies_with_unrecognised_place` | 1 | The SEC gives the place as a code no country matches |

## The generated layer

All of the following is generated by `etl/generate.py`, deterministically from
seed `20260929`.

| Label | Count | |
|---|---:|---|
| Institution | 40 | Banks and payment firms that hold the generated accounts |
| Customer | 3,000 | 2,441 people and 559 businesses |
| Account | 5,411 | |
| Device | 3,653 | Devices accounts sign in from |
| Loan | 1,200 | |
| WatchlistEntry | 60 | A scenario watchlist; 40 entries name generated customers |
| Alert | 30 | Raised by rule over the generated payments |

Payments are edges: 36,681 `TRANSFER` edges between accounts.

**What this layer demonstrates, it does not report.** A query over it shows the
kind of question the graph answers. Its numbers say nothing about any real
person, company, bank or payment.

### Nothing generated touches a real organisation

The generated layer has its own institutions and its own customers. It never
opens an account at a bank the real layer names, never makes a real company a
customer, and never puts a real name on the watchlist. A generated fraud ring
at a real bank would be an invented allegation about it.

The two layers meet only at neutral reference data: a generated customer is
`BASED_IN` a real country, a generated business is `IN_INDUSTRY` a real
industry, and a generated account is `DENOMINATED_IN` a real currency. The
loader refuses any other edge from the generated layer to the real one, and a
test checks that no generated name is the name of anything real.

### Where the generated layer is anchored on real data

| Generated | Anchored on |
|---|---|
| Where customers and institutions are | Real countries, weighted by the square root of GDP; 74 countries have customers |
| The currency of each account | The real currency of its country, from the country file; only currencies with a published rate for every month are used |
| The dollar value of each payment | Its amount converted at the real ECB rate for its month. A test checks every payment. |
| Industries of business customers | Real industry codes from the SEC's list |
| The national bad-loan benchmark beside the generated loan book | World Bank |

### What is planted

Fraud teams look for shapes. Three are planted among the background payments,
and every planted payment carries its `pattern`, so a detection query can be
scored against the truth.

| Pattern | Payments | Shape |
|---|---:|---|
| `background` | 36,000 | Random payments between random accounts |
| `structuring` | 321 | Many payments each just under a 10,000-dollar threshold into one account in one month |
| `mule` | 248 | An account collects from many and forwards nearly all of it to one |
| `ring` | 112 | Money goes round a circle of three to six accounts in a few days, the accounts sharing a device |

### Alerts are counted, not drawn

An alert is raised wherever the structuring rule fires: five or more payments
between 9,000 and 10,000 dollars into one account in one calendar month. The
rule is applied to all payments, planted or not, and the alert records the
payments that fired it. A test checks that every alert matches the rule and
that nothing else does.

### Names

Customer, institution and watchlist names are coined from invented syllables
(`Rorah Lumhurst`, `Rhovane Digital Bank`). A test checks that no generated
name equals the name of any real company, bank, holding company or legal
entity in the graph. A resemblance to a real person or firm outside the graph
is possible and unchecked.
