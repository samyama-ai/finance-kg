# Finance Knowledge Graph

**69,437 nodes. 149,387 edges. Real companies, banks, legal entities and
exchange rates from 11 public sources, with generated banking activity kept
apart from them.**

![Finance demo](demo/finance-kg.gif)

> Part of the **Samyama** ecosystem — loaded into and queried via the graph engine at [samyama-ai/samyama-graph](https://github.com/samyama-ai/samyama-graph).
> This repo holds the loader and source-data specifics for the KG.

<a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache_2.0-blue" alt="License"></a>

---

## What is real and what is not

| Layer | Nodes | Edges | What it holds |
|---|---:|---:|---|
| **Real** | 56,043 | 83,041 | 8,004 US-listed companies with filings and reported figures, 4,231 US banks and 4,117 bank failures, 16,934 legal entities in India and their parents, 1,931 exchanges, exchange rates for 31 currencies, countries with World Bank indicators |
| **Generated** | 13,394 | 66,346 | 40 institutions, 3,000 customers, 5,411 accounts, 36,681 payments, 1,200 loans, a watchlist, alerts |

**Nothing generated is attached to a real organisation.** Nobody publishes
accounts, payments or loans, so they are invented. They belong to invented
institutions and invented customers, and they meet the real layer only at
countries, currencies, exchange rates and industries. A generated fraud ring
at a real bank would be an invented allegation about it, and the loader
refuses any such edge.

**What the generated layer demonstrates, it does not report.** Its numbers
describe no real person, company, bank or payment.

Every node and edge carries `provenance` (`real` or `synthetic`), so any query
can tell the two apart.

## Terms of use

Every source is public domain, CC0, CC BY 4.0, or free to reuse with the
publisher cited, so the graph may be used for any purpose, including commercial
use and public display. Credits owed:

> Source: World Bank, World Development Indicators.
> Source: European Central Bank.

Details, and the one change made to ECB figures, are in
[`docs/data-provenance.md`](docs/data-provenance.md).

---

## A question on real data

> *"Starting from one legal entity in India, who are its parents, all the way
> up?"*

```cypher
MATCH (e:LegalEntity)-[:CONSOLIDATED_BY*1..6]->(p:LegalEntity)
WHERE e.lei = "335800DJLEUSVXIZV875"
MATCH (p)-[:LOCATED_IN]->(k:Country)
WITH DISTINCT p.name AS parent, k.name AS country, p.lei AS lei
RETURN parent, country, lei
ORDER BY parent, lei
```

| Parent | Country |
|---|---|
| TATA HOUSING DEVELOPMENT COMPANY LIMITED | India |
| TATA REALTY AND INFRASTRUCTURE LIMITED | India |
| TATA SONS PRIVATE LIMITED | India |

The entity is Tata Value Homes Limited. Source: GLEIF, CC0.

> *"Which foreign countries ultimately own the most legal entities in India?"*

| Parent country | Indian entities | Parents |
|---|---:|---:|
| US | 961 | 532 |
| UK | 309 | 105 |
| Germany | 219 | 135 |
| Japan | 210 | 104 |
| France | 126 | 58 |

## A question on generated data

> *"Which sets of three accounts passed a large sum from one to the next and
> back to the start?"*

```cypher
MATCH (a:Account)-[t1:TRANSFER]->(b:Account)-[t2:TRANSFER]->(c:Account)-[t3:TRANSFER]->(a)
WHERE t1.amount_usd >= 15000.0 AND t2.amount_usd >= 15000.0
  AND t3.amount_usd >= 15000.0 AND a.id < b.id AND a.id < c.id
WITH a.account_no AS first, b.account_no AS second, c.account_no AS third,
     round(t1.amount_usd) AS sent_usd, round(t3.amount_usd) AS returned_usd
RETURN first, second, third, sent_usd, returned_usd
ORDER BY sent_usd DESC, first
LIMIT 10
```

| First | Second | Third | Sent, USD | Returned, USD |
|---|---|---|---:|---:|
| AC-0001753 | AC-0003605 | AC-0005234 | 68,316 | 69,362 |
| AC-0000239 | AC-0003613 | AC-0003877 | 66,714 | 63,658 |
| AC-0002511 | AC-0005095 | AC-0004692 | 44,131 | 44,997 |

The rings are planted. Every planted payment carries its `pattern`, so a
detection query like this one can be scored against the truth.

---

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

python -m etl.download_data          # fetch the 11 public sources into data/raw/
python -m etl.loader --dry-run       # build and check the graph; no engine needed
python -m demo.demo                  # narrated demo on the embedded engine
pytest                               # needs no download
```

The download takes about 30 minutes, most of it the SEC's one-request-per-
company profiles at the rate the SEC allows, and about 500 MB of transfer, most
of it the GLEIF file that is read once and reduced. No account or API key is
needed. Set `SEC_USER_AGENT` to your organisation and contact address before
downloading; the SEC asks automated clients to identify themselves.

### Load into a running Samyama server

```bash
python -m etl.loader --url http://127.0.0.1:8080 --graph finance
```

The full graph loads in about five minutes. `--reset` deletes everything in
the graph it is pointed at.

### Loader options

| Option | Default | |
|---|---|---|
| `--layers real` | `all` | Load only the public data |
| `--scale 0.2` | `1.0` | Size of the generated layer |
| `--seed` | `20260929` | Same seed, same graph |
| `--graph` | `default` | Graph, or tenant, on the server |
| `--dry-run` | | Write the load as Cypher to `data/generated/load.cypher` |

---

## Schema

**20 node labels** — Country, Currency, ExchangeRate, Exchange, State,
Industry, Company, Filing, Regulator, HoldingCompany, Bank, BankFailure,
LegalEntity, Institution, Customer, Account, Device, Loan, WatchlistEntry,
Alert

**26 edge types** — USES, RATE_OF, LOCATED_IN, PART_OF, LISTED_ON, IN_INDUSTRY,
BASED_IN, FILED_BY, SAME_AS, SUPERVISED_BY, CONTROLLED_BY, OCCURRED_IN,
FAILURE_OF, CONSOLIDATED_BY, BRANCH_OF, OWNED_BY, HELD_AT, DENOMINATED_IN,
SIGNED_IN_FROM, TRANSFER, BORROWED, DISBURSED_TO, ISSUED_BY, GUARANTEES,
LISTED_AS, FLAGS

The paths most questions walk:

```
real        (Bank)-[:CONTROLLED_BY]->(HoldingCompany)
real        (Bank)-[:LOCATED_IN]->(State)<-[:OCCURRED_IN]-(BankFailure)
real        (LegalEntity)-[:CONSOLIDATED_BY]->(LegalEntity)-[:LOCATED_IN]->(Country)
real        (Filing)-[:FILED_BY]->(Company)-[:IN_INDUSTRY]->(Industry)
real        (ExchangeRate)-[:RATE_OF]->(Currency)<-[:USES]-(Country)

generated   (Account)-[:TRANSFER]->(Account)-[:OWNED_BY]->(Customer)
generated   (Alert)-[:FLAGS]->(Account)-[:HELD_AT]->(Institution)
generated   (Customer)-[:LISTED_AS]->(WatchlistEntry)
generated   (Customer)-[:GUARANTEES]->(Customer)-[:BORROWED]->(Loan)

across      (Customer)-[:BASED_IN]->(Country)          the only real things a
across      (Account)-[:DENOMINATED_IN]->(Currency)    generated edge may reach
across      (Customer)-[:IN_INDUSTRY]->(Industry)
```

See [`docs/schema.md`](docs/schema.md) for every property and count.

## Data sources

| Source | Supplies | Terms |
|---|---|---|
| [US Securities and Exchange Commission](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) | Companies, tickers, industries, filings, reported figures | Public domain |
| [Federal Deposit Insurance Corporation](https://banks.data.fdic.gov/bankfind-suite/bulkData) | Banks, holding companies, bank failures | Public domain |
| [GLEIF](https://www.gleif.org/en/lei-data/gleif-golden-copy) | Legal entities in India and their parents | CC0 |
| [European Central Bank](https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html) | Exchange rates | Free reuse, ECB cited |
| [World Bank](https://data.worldbank.org/indicator/FS.AST.PRVT.GD.ZS) | Country financial indicators | CC BY 4.0 |
| [Wikidata](https://www.wikidata.org) | Stock exchanges | CC0 |
| [datasets/country-codes](https://github.com/datasets/country-codes), [datasets/currency-codes](https://github.com/datasets/currency-codes) | Countries and currencies | Public domain |

None of this data is committed to the repo. `data/` is git-ignored.

## Query catalog

Sixteen questions, in [`benchmarks/queries.py`](benchmarks/queries.py).
`both` means generated activity measured against real reference data.

| Id | Layer | Question |
|---|---|---|
| FN01 | real | Bank failures, year by year |
| FN02 | real | Holding companies that control the most banks |
| FN03 | real | Where banks failed, and how many remain |
| FN04 | real | Who ultimately owns an Indian company |
| FN05 | real | Which countries own the most Indian companies |
| FN06 | real | Industries by reported revenue |
| FN07 | real | Foreign companies listed in the US |
| FN08 | real | A currency against the dollar |
| FN09 | generated | Money going round in a circle |
| FN10 | generated | Accounts flagged for structuring |
| FN11 | generated | Devices shared between customers |
| FN12 | generated | Who paid a watchlisted customer |
| FN13 | both | Cross-border payment corridors |
| FN14 | both | Troubled loans against national bad-loan rates |
| FN15 | generated | Who is on the hook when a borrower defaults |
| FN16 | both | How much of this graph is real |

**Every answer is checked.** Each query is written a second time in plain
Python, and the two must agree on the rows, their order, and which rows a
`LIMIT` kept.

```bash
python -m benchmarks.run             # run, time and check all sixteen
```

## MCP server

```bash
python -m mcp_server.server --list-tools                   # 17 tools; needs no engine
python -m mcp_server.server                                # embedded
FINANCE_KG_URL=http://127.0.0.1:8080 python -m mcp_server.server --graph finance
```

Every tool returns its `layer` with the answer, and a sentence saying what that
means, so an agent can tell a real finding from a generated one.

## Structure

```
etl/
  download_data.py   fetch the public sources
  real_layer.py      public data -> nodes and edges
  generate.py        the generated banking activity
  loader.py          build, check, load, verify
schema/              the schema, indexes and invariants
benchmarks/          the query catalog, its Python reference, the runner
mcp_server/          the MCP server
demo/                the narrated demo
docs/                schema, data provenance, engine notes
tests/               pytest, on made-up fixture data
```

## Documentation

| Document | What it covers |
|---|---|
| [`DATASET_CARD.md`](DATASET_CARD.md) | The dataset in one page: contents, terms, intended use, limits |
| [`docs/schema.md`](docs/schema.md) | Every property and count |
| [`docs/data-provenance.md`](docs/data-provenance.md) | Sources, terms of use, what is generated and how |
| [`docs/engine-notes.md`](docs/engine-notes.md) | Engine behaviour and load times |

## Known limits

- **India has entities, not figures.** GLEIF gives names, addresses and
  parents. Financial figures exist only for companies that file with the SEC.
- **Banks are US only.** Indian banks appear as legal entities, found by the
  word BANK in their name.
- **Company profiles and filings cover 2,500 of the 8,004 companies**, the
  largest by the SEC's ordering.
- **Companies reporting under IFRS have no figures**, since the SEC's frames
  cover US GAAP.
- **The full graph takes about five minutes to load** into the embedded
  engine. Use `--scale` for a quicker one.

Details are in [`docs/data-provenance.md`](docs/data-provenance.md).

## License

Apache 2.0 for the code. The data is not covered by this licence: each source
keeps its publisher's terms.
