# Finance KG — Design Notes

The full schema, with indexes and invariants, is
[`schema/finance_kg.cypher`](../schema/finance_kg.cypher). Where the data comes
from is [`data-provenance.md`](data-provenance.md).

## Two layers, one graph

Every node and every edge carries `provenance`. Every node also carries `source`.

| `provenance` | `source` | Meaning |
|---|---|---|
| `real` | the dataset's URL | Downloaded from a public source |
| `synthetic` | `generated` | Invented from a seed |

The real layer is organisations and reference data. The generated layer is
banking activity. A generated edge may reach a real Country, Currency or
Industry, and no other real node.

## Node labels

### Real

| Label | Count | Key fields |
|---|---:|---|
| Country | 249 | `iso3`, `iso2`, `name`, `region`, `sub_region`, `gdp_usd`, `inflation_pct`, `lending_rate_pct`, `private_credit_pct_gdp`, `bank_npl_pct`, `bank_capital_to_assets_pct`, `market_cap_pct_gdp`, `account_ownership_pct` |
| Currency | 178 | `code`, `name`, `numeric_code`, `minor_unit` |
| ExchangeRate | 2,457 | `currency`, `month`, `date`, `year`, `month_no`, `per_eur`, `per_usd` |
| Exchange | 1,931 | `mic`, `name`, `wikidata_id`, `iso3` |
| State | 55 | `code`, `name` |
| Industry | 340 | `sic`, `name` |
| Company | 8,004 | `cik`, `name`, `ticker`, `tickers`, `category`, `entity_type`, `fiscal_year_end`, `incorporated_in`, `city`, `lei`, `fiscal_year`, `assets_usd`, `liabilities_usd`, `equity_usd`, `revenue_usd`, `net_income_usd`, `fiscal_period_end` |
| Filing | 14,216 | `accession`, `form`, `filed`, `period`, `year` |
| Regulator | 3 | `code`, `name` |
| HoldingCompany | 3,328 | `rssd_id`, `name` |
| Bank | 4,231 | `cert`, `name`, `city`, `state`, `charter_class`, `specialisation`, `community_bank`, `established`, `offices`, `assets_usd`, `deposits_usd`, `equity_usd`, `net_income_usd`, `return_on_assets_pct`, `return_on_equity_pct`, `reported` |
| BankFailure | 4,117 | `name`, `cert`, `city`, `state`, `failed`, `year`, `resolution`, `resolution_type`, `insurance_fund`, `charter_class`, `assets_usd`, `deposits_usd`, `estimated_loss_usd` |
| LegalEntity | 16,934 | `lei`, `name`, `city`, `region`, `country`, `jurisdiction`, `category`, `legal_form`, `status`, `registration_status`, `registered`, `is_bank` |

Every World Bank figure on a Country has a companion `_year` property, such as
`gdp_usd_year`. The indicators stop in different years, so a figure is never
stored without the year it belongs to. A country with no figure has no property
at all, rather than a zero.

A Company has financial figures only where the SEC's XBRL frames hold them:
5,531 of 8,004 have at least one. `fiscal_year` is 2024 on those and absent on
the rest.

### Generated

| Label | Count | Key fields |
|---|---:|---|
| Institution | 40 | `name`, `kind`, `iso3`, `founded` |
| Customer | 3,000 | `name`, `kind`, `iso3`, `onboarded`, `kyc_status`, `risk_rating` |
| Account | 5,411 | `account_no`, `kind`, `currency`, `iso3`, `opened`, `status`, `balance` |
| Device | 3,653 | `kind`, `first_seen` |
| Loan | 1,200 | `principal`, `currency`, `principal_usd`, `rate_pct`, `term_months`, `issued`, `status` |
| WatchlistEntry | 60 | `name`, `list_name`, `reason`, `listed` |
| Alert | 30 | `kind`, `month`, `raised`, `transfers`, `amount_usd`, `status` |

## Edge types

### Real

| Edge | From → To | Properties | Count |
|---|---|---|---:|
| USES | Country → Currency | | 253 |
| RATE_OF | ExchangeRate → Currency | | 2,457 |
| LOCATED_IN | Exchange, Bank, LegalEntity → Country or State | | 23,022 |
| PART_OF | State → Country | | 55 |
| LISTED_ON | Company → Exchange | `ticker` | 8,110 |
| IN_INDUSTRY | Company → Industry | | 2,372 |
| BASED_IN | Company → Country | | 2,253 |
| FILED_BY | Filing → Company | | 14,216 |
| SAME_AS | Company → LegalEntity | | 4 |
| SUPERVISED_BY | Bank → Regulator | | 4,229 |
| CONTROLLED_BY | Bank → HoldingCompany | | 3,548 |
| OCCURRED_IN | BankFailure → State | | 4,117 |
| FAILURE_OF | BankFailure → Bank | | 7 |
| CONSOLIDATED_BY | LegalEntity → LegalEntity | `level`, `since` | 18,295 |
| BRANCH_OF | LegalEntity → LegalEntity | `since` | 103 |

`LOCATED_IN` leaves an Exchange for a Country (1,857), a Bank for a State
(4,231) and a LegalEntity for a Country (16,934).

`CONSOLIDATED_BY.level` is `direct` or `ultimate`, GLEIF's two kinds of
consolidating parent. `FAILURE_OF` is rare because a failed bank is usually
no longer an active one.

### Generated

| Edge | From → To | Properties | Count |
|---|---|---|---:|
| BASED_IN | Institution, Customer → Country | | 3,040 |
| IN_INDUSTRY | Customer → Industry | | 559 |
| OWNED_BY | Account → Customer | | 5,411 |
| HELD_AT | Account → Institution | | 5,411 |
| DENOMINATED_IN | Account → Currency | | 5,411 |
| SIGNED_IN_FROM | Account → Device | | 5,563 |
| TRANSFER | Account → Account | `amount`, `currency`, `amount_usd`, `date`, `month`, `channel`, `cross_border`, `pattern` | 36,681 |
| BORROWED | Customer → Loan | | 1,200 |
| DISBURSED_TO | Loan → Account | | 1,200 |
| ISSUED_BY | Loan → Institution | | 1,200 |
| GUARANTEES | Customer → Customer | `since` | 600 |
| LISTED_AS | Customer → WatchlistEntry | | 40 |
| FLAGS | Alert → Account | | 30 |

`BASED_IN` and `IN_INDUSTRY` are drawn by both layers. They are real when they
leave a Company and generated when they leave a Customer or an Institution.

## Design decisions

**Payments are edges, not nodes.** A payment has two ends and its own
properties, which is what an edge is. Ring detection is then a three-edge
pattern rather than a six-join query.

**Edges carry provenance, not only nodes.** A generated customer is `BASED_IN`
a real country. The provenance of an edge cannot be read off one end of it.

**The generated layer is sealed off from real organisations.** Invariant 3 in
the schema file, enforced before every load. See `data-provenance.md`.

**Dollar values are computed at the real rate for the month.** Every
`TRANSFER` carries `amount` in the account's currency and `amount_usd` at the
ECB rate for its month, so totals across currencies are comparable and the
computation is checkable.

**Alerts are raised by rule.** The structuring rule runs over every payment;
an alert is one place it fired. A second set of invented alerts would disagree
with the payments.

**Ids are readable and deterministic.** `country:IND`, `currency:INR`,
`company:320193` (the SEC's CIK), `bank:3511` (the FDIC certificate),
`lei:335800DJLEUSVXIZV875`, `exchange:XNSE`, `state:NY`,
`rate:INR:2025-12`, `customer:001699`. The same seed always produces the same
generated ids.
