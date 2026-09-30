---
license: other
pretty_name: Finance Knowledge Graph
tags:
  - knowledge-graph
  - samyama
  - property-graph
  - finance
  - banking
  - synthetic
language:
  - en
size_categories:
  - 10K<n<100K
---

# Dataset Card for `finance-kg`

**69,437 nodes. 149,387 edges. Real companies, banks, legal entities and
exchange rates from 11 public sources, with generated banking activity kept
apart from them.**

> Part of the **Samyama** ecosystem. This card describes the dataset; the repository
> holds the loader and source-data specifics.

## Summary

A property graph with two layers. The real layer is organisations and
reference data: US-listed companies with their filings and reported figures,
US banks with their holding companies and failures, legal entities in India
with their parent companies, stock exchanges, currencies and exchange rates,
and countries with World Bank indicators. The generated layer is banking
activity: institutions, customers, accounts, payments, loans, a watchlist and
alerts.

| Layer | Nodes | Edges |
|---|---:|---:|
| Real | 56,043 | 83,041 |
| Generated | 13,394 | 66,346 |

**80.7% of nodes are real.** Every node and edge carries `provenance` (`real`
or `synthetic`).

**Nothing generated is attached to a real organisation.** A generated edge may
reach a real country, currency or industry, and no other real node. The loader
refuses anything else.

## Intended use

- Demonstrating graph queries over finance: ownership chains, bank failure
  contagion, payment rings, structuring, watchlist exposure.
- Teaching and testing: loaders, query engines, MCP tools, agents.

## Not suitable for

- **Any claim about a real person's or company's banking activity.** The
  graph holds none. Every account, payment, loan, alert and watchlist entry is
  invented and belongs to an invented customer at an invented institution.
- **Compliance screening.** The watchlist is a scenario list of invented names.
- **Investment decisions.** Company figures are five reported items for one
  fiscal year, for the companies the SEC's frames cover.

## Structure

**20 node labels** -- Country, Currency, ExchangeRate, Exchange, State,
Industry, Company, Filing, Regulator, HoldingCompany, Bank, BankFailure,
LegalEntity, Institution, Customer, Account, Device, Loan, WatchlistEntry,
Alert

**26 edge types** -- USES, RATE_OF, LOCATED_IN, PART_OF, LISTED_ON,
IN_INDUSTRY, BASED_IN, FILED_BY, SAME_AS, SUPERVISED_BY, CONTROLLED_BY,
OCCURRED_IN, FAILURE_OF, CONSOLIDATED_BY, BRANCH_OF, OWNED_BY, HELD_AT,
DENOMINATED_IN, SIGNED_IN_FROM, TRANSFER, BORROWED, DISBURSED_TO, ISSUED_BY,
GUARANTEES, LISTED_AS, FLAGS

| Label | Count | Layer |
|---|---:|---|
| Country | 249 | real |
| Currency | 178 | real |
| ExchangeRate | 2,457 | real |
| Exchange | 1,931 | real |
| State | 55 | real |
| Industry | 340 | real |
| Company | 8,004 | real |
| Filing | 14,216 | real |
| Regulator | 3 | real |
| HoldingCompany | 3,328 | real |
| Bank | 4,231 | real |
| BankFailure | 4,117 | real |
| LegalEntity | 16,934 | real |
| Institution | 40 | generated |
| Customer | 3,000 | generated |
| Account | 5,411 | generated |
| Device | 3,653 | generated |
| Loan | 1,200 | generated |
| WatchlistEntry | 60 | generated |
| Alert | 30 | generated |

Every property and edge count is in [`docs/schema.md`](docs/schema.md).

## Provenance and licence

The repository's code is Apache 2.0. **That licence does not cover the data.**
Each source keeps its publisher's terms, listed here. The frontmatter is
therefore `license: other`.

| Source | Supplies | Terms |
|---|---|---|
| [US Securities and Exchange Commission](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) | Companies, tickers, exchanges, industries, filings, reported figures | Public domain (US government work) |
| [US Federal Deposit Insurance Corporation](https://banks.data.fdic.gov/bankfind-suite/bulkData) | Banks, holding companies, bank failures | Public domain (US government work) |
| [GLEIF](https://www.gleif.org/en/lei-data/gleif-golden-copy) | Legal entities and parent relationships | CC0 1.0 |
| [European Central Bank](https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html) | Euro reference exchange rates | Free reuse, ECB cited as source |
| [World Bank](https://data.worldbank.org/indicator/FS.AST.PRVT.GD.ZS), World Development Indicators | Country financial indicators | CC BY 4.0 |
| [Wikidata](https://www.wikidata.org) | Stock exchanges | CC0 1.0 |
| [datasets/country-codes](https://github.com/datasets/country-codes) | Countries | ODC-PDDL 1.0 |
| [datasets/currency-codes](https://github.com/datasets/currency-codes) | Currencies | ODC-PDDL 1.0 |

All allow any use, including commercial use and public display. Credits owed:
*Source: World Bank, World Development Indicators* and *Source: European
Central Bank*. The one change made to ECB figures, a derived dollar rate, is
stated in [`docs/data-provenance.md`](docs/data-provenance.md).

This is a reading of each publisher's stated terms, made on 2026-09-29. It is
not legal advice.

## How the generated layer is made

Generated by `etl/generate.py`, deterministically from seed `20260929`.

- **Names are coined** from invented syllables. A test checks that no generated
  name equals the name of anything real in the graph.
- **Payments are priced at real rates.** Each carries its amount in the
  account's currency and its dollar value at the ECB rate for its month.
- **Three patterns are planted** among random payments: rings, structuring
  under a 10,000-dollar threshold, and mule accounts. Every planted payment
  records its pattern, so detection can be scored.
- **Alerts are raised by rule**, not drawn: five or more payments between
  9,000 and 10,000 dollars into one account in one month.

## Personal and sensitive data

The real layer names organisations, and people only where an organisation's
name contains one, as some bank holding companies' do. GLEIF sole proprietors,
who trade under their own names, are left out. The generated layer names
nobody real.

## Reproducing

```bash
pip install -e ".[dev]"
python -m etl.download_data          # fetch the 11 public sources
python -m etl.loader --dry-run       # build and check; no engine needed
python -m etl.loader --url http://127.0.0.1:8080 --graph finance
```

No snapshot is published. No downloaded data is committed to the repository.

## Known limitations

- **India has entities, not figures.** GLEIF supplies names, addresses and
  parents. Reported figures exist only for companies that file with the SEC.
- **Banks are US only.** Indian banks appear as GLEIF legal entities, found by
  the word BANK in their name.
- **Company profiles and filings** cover the first 2,500 of 8,004 companies in
  the SEC's list; **reported figures** cover 5,531, those in the SEC's US GAAP
  frames.
- **Exchange rates are month-end**, for 31 currencies the ECB quotes.
- **US states are the only sub-national places**, because FDIC data is by
  state.

Full detail is in [`docs/data-provenance.md`](docs/data-provenance.md).

## Verification

- 16 catalog queries, each checked against an independent Python
  implementation on the full graph.
- The loader counts every label and edge type in the graph against what it
  sent, and refuses to load a graph that fails its integrity checks.
- The counts on this card are checked against a fresh build by the test suite.

## Links

| | |
|---|---|
| Samyama Graph | [github.com/samyama-ai/samyama-graph](https://github.com/samyama-ai/samyama-graph) |
| The Book | [samyama-ai.github.io/samyama-graph-book](https://samyama-ai.github.io/samyama-graph-book/) |
| Contact | [samyama.dev/contact](https://samyama.dev/contact) |
