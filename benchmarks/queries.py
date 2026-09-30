"""Query catalog for the finance knowledge graph.

Each entry is a question somebody in banking, compliance or investment
research actually asks. The `why_graph` field records why it is awkward in a
relational store -- most walk a chain of unknown length, or look for a shape
in the payments rather than a row.

`layer` says what the answer rests on, and it matters how the answer is read:

  real       public data only. The answer is a statement about the world.
  synthetic  generated data only. The answer shows the question being
             answered; its numbers describe nothing real.
  both       generated activity measured against real reference data, such as
             a generated payment converted at a real exchange rate.

No query joins a generated customer, account or payment to a real company or
bank. The graph holds no such edge.

Written defensively, in the style Samyama v1.7.0 required, so the catalog runs
on an older server as well as a current one:
  * String literals are double-quoted.
  * Every query projects through a `WITH` and sorts on an alias that `WITH`
    established, never on one introduced in the `RETURN` that sorts on it.
  * A second MATCH leads with the variable it shares with the first.
  * Under a `LIMIT`, the `ORDER BY` ends with a column that breaks ties.

`params` holds the defaults for the `$name` placeholders in `cypher`. They are
substituted by `render()` as escaped literals, never pasted in as text.
"""
from __future__ import annotations

import re

from etl.helpers import cypher_literal

QUERIES: list[dict] = [
    {
        "id": "FN01",
        "title": "Bank failures, year by year",
        "layer": "real",
        "question": ("How many US banks failed each year, how large were they, and "
                     "what did the failures cost the insurance fund?"),
        "why_graph": ("Simple on its own. It is the entry point: each failure is a "
                      "node that also knows its state, and through the state the "
                      "banks still operating there."),
        "params": {"from_year": 2007, "to_year": 2026},
        "cypher": """
MATCH (f:BankFailure)
WHERE f.year >= $from_year AND f.year <= $to_year
WITH f.year AS year, count(f) AS failures,
     round(sum(f.assets_usd) / 1000000000.0) AS assets_usd_billion,
     round(sum(coalesce(f.estimated_loss_usd, 0)) / 1000000000.0) AS loss_usd_billion
RETURN year, failures, assets_usd_billion, loss_usd_billion
ORDER BY year
""",
    },
    {
        "id": "FN02",
        "title": "Holding companies that control the most banks",
        "layer": "real",
        "question": ("Which holding companies control the most banks, and how much "
                     "do those banks hold in assets?"),
        "why_graph": ("Control is a relationship, not a column. One holding "
                      "company, many banks, summed from the holding company's side."),
        "params": {"limit": 10},
        "cypher": """
MATCH (b:Bank)-[:CONTROLLED_BY]->(h:HoldingCompany)
WITH h.name AS holding_company, count(b) AS banks,
     round(sum(b.assets_usd) / 1000000000.0) AS assets_usd_billion
RETURN holding_company, banks, assets_usd_billion
ORDER BY banks DESC, assets_usd_billion DESC, holding_company
LIMIT $limit
""",
    },
    {
        "id": "FN03",
        "title": "Where banks failed, and how many remain",
        "layer": "real",
        "question": ("Which states lost the most banks in the period, and how many "
                     "banks operate there today?"),
        "why_graph": ("Two different facts about the same place, from two "
                      "datasets. The state is the node where they meet."),
        "params": {"from_year": 2008, "limit": 10},
        "cypher": """
MATCH (f:BankFailure)-[:OCCURRED_IN]->(s:State)
WHERE f.year >= $from_year
WITH s, count(f) AS failures
MATCH (s)<-[:LOCATED_IN]-(b:Bank)
WITH s.name AS state, failures, count(b) AS banks_today
RETURN state, failures, banks_today
ORDER BY failures DESC, state
LIMIT $limit
""",
    },
    {
        "id": "FN04",
        "title": "Who ultimately owns an Indian company",
        "layer": "real",
        "question": ("Starting from one legal entity, who are its parents, all the "
                     "way up, and where is each one?"),
        "why_graph": ("The chain has no fixed length. A variable-length path walks "
                      "it to the top; SQL needs a recursive query and a guess at "
                      "the depth."),
        "params": {"lei": "335800DJLEUSVXIZV875"},
        "cypher": """
MATCH (e:LegalEntity)-[:CONSOLIDATED_BY*1..6]->(p:LegalEntity)
WHERE e.lei = $lei
MATCH (p)-[:LOCATED_IN]->(k:Country)
WITH DISTINCT p.name AS parent, k.name AS country, p.lei AS lei
RETURN parent, country, lei
ORDER BY parent, lei
""",
    },
    {
        "id": "FN05",
        "title": "Which countries own the most Indian companies",
        "layer": "real",
        "question": ("Counting by ultimate parent, which foreign countries "
                     "consolidate the most legal entities in India?"),
        "why_graph": ("From an entity to its ultimate parent to that parent's "
                      "country, then grouped. Three hops across two kinds of thing."),
        "params": {"iso3": "IND", "limit": 10},
        "cypher": """
MATCH (e:LegalEntity)-[:LOCATED_IN]->(home:Country)
WHERE home.iso3 = $iso3
MATCH (e)-[c:CONSOLIDATED_BY]->(p:LegalEntity)
WHERE c.level = "ultimate"
MATCH (p)-[:LOCATED_IN]->(k:Country)
WHERE k.iso3 <> $iso3
WITH k.name AS parent_country, count(DISTINCT e) AS entities,
     count(DISTINCT p) AS parents
RETURN parent_country, entities, parents
ORDER BY entities DESC, parent_country
LIMIT $limit
""",
    },
    {
        "id": "FN06",
        "title": "Industries by reported revenue",
        "layer": "real",
        "question": ("Which industries reported the most revenue, and across how "
                     "many companies?"),
        "why_graph": ("The figures come from one SEC dataset and the industry "
                      "from another. The company node joins them."),
        "params": {"limit": 10},
        "cypher": """
MATCH (c:Company)-[:IN_INDUSTRY]->(i:Industry)
WHERE c.revenue_usd IS NOT NULL
WITH i.name AS industry, count(c) AS companies,
     round(sum(c.revenue_usd) / 1000000000.0) AS revenue_usd_billion
RETURN industry, companies, revenue_usd_billion
ORDER BY revenue_usd_billion DESC, industry
LIMIT $limit
""",
    },
    {
        "id": "FN07",
        "title": "Foreign companies listed in the US",
        "layer": "real",
        "question": ("Which countries, other than the US, are home to the most "
                     "companies that file with the SEC?"),
        "why_graph": ("A listing is a link between a company in one country and "
                      "an exchange in another."),
        "params": {"limit": 10},
        "cypher": """
MATCH (c:Company)-[:BASED_IN]->(k:Country)
WHERE k.iso3 <> "USA"
WITH k.name AS country, count(c) AS companies
RETURN country, companies
ORDER BY companies DESC, country
LIMIT $limit
""",
    },
    {
        "id": "FN08",
        "title": "A currency against the dollar",
        "layer": "real",
        "question": "How has this currency moved against the US dollar, year end to year end?",
        "why_graph": ("Each month's rate is a node hanging off its currency, so "
                      "the same rate that answers this also prices every "
                      "generated payment in that currency."),
        "params": {"currency": "INR"},
        "cypher": """
MATCH (r:ExchangeRate)-[:RATE_OF]->(c:Currency)
WHERE c.code = $currency AND r.month_no = 12
WITH r.year AS year, r.date AS rate_date, r.per_usd AS per_usd
RETURN year, rate_date, per_usd
ORDER BY year
""",
    },
    {
        "id": "FN09",
        "title": "Money going round in a circle",
        "layer": "synthetic",
        "question": ("Which sets of three accounts passed a large sum from one to "
                     "the next and back to the start?"),
        "why_graph": ("A ring is a shape, not a row. The pattern below is the "
                      "whole query; in SQL it is a three-way self-join on the "
                      "payments table."),
        "params": {"min_usd": 15000.0, "limit": 10},
        "cypher": """
MATCH (a:Account)-[t1:TRANSFER]->(b:Account)-[t2:TRANSFER]->(c:Account)-[t3:TRANSFER]->(a)
WHERE t1.amount_usd >= $min_usd AND t2.amount_usd >= $min_usd
  AND t3.amount_usd >= $min_usd AND a.id < b.id AND a.id < c.id
WITH a.account_no AS first, b.account_no AS second, c.account_no AS third,
     round(t1.amount_usd) AS sent_usd, round(t3.amount_usd) AS returned_usd
RETURN first, second, third, sent_usd, returned_usd
ORDER BY sent_usd DESC, first
LIMIT $limit
""",
    },
    {
        "id": "FN10",
        "title": "Accounts flagged for structuring",
        "layer": "synthetic",
        "question": ("Which accounts were flagged for receiving repeated payments "
                     "just under the reporting threshold, and who holds them?"),
        "why_graph": ("From the alert to the account, then out two ways at once: "
                      "to its owner and to the institution holding it."),
        "params": {"limit": 10},
        "cypher": """
MATCH (al:Alert)-[:FLAGS]->(a:Account)-[:OWNED_BY]->(c:Customer),
      (a)-[:HELD_AT]->(i:Institution)
WHERE al.kind = "structuring"
WITH a.account_no AS account, c.name AS customer, i.name AS institution,
     al.month AS month, al.transfers AS transfers, round(al.amount_usd) AS amount_usd
RETURN account, customer, institution, month, transfers, amount_usd
ORDER BY amount_usd DESC, account
LIMIT $limit
""",
    },
    {
        "id": "FN11",
        "title": "Devices shared between customers",
        "layer": "synthetic",
        "question": ("Which devices were used to sign in to the accounts of "
                     "several different customers?"),
        "why_graph": ("Two customers who share nothing on paper are linked "
                      "through a device neither of them owns. That link exists "
                      "only as a path."),
        "params": {"min_customers": 3, "limit": 10},
        "cypher": """
MATCH (c:Customer)<-[:OWNED_BY]-(a:Account)-[:SIGNED_IN_FROM]->(d:Device)
WITH d.id AS device, d.kind AS kind, count(DISTINCT c) AS customers,
     count(DISTINCT a) AS accounts
WHERE customers >= $min_customers
RETURN device, kind, customers, accounts
ORDER BY customers DESC, device
LIMIT $limit
""",
    },
    {
        "id": "FN12",
        "title": "Who paid a watchlisted customer",
        "layer": "synthetic",
        "question": ("For each customer on the watchlist, how many other customers "
                     "sent them money, and how much?"),
        "why_graph": ("Exposure is one step beyond the list. From the watchlist "
                      "entry to the customer, their accounts, the payments in, "
                      "and the customers behind those."),
        "params": {"limit": 10},
        "cypher": """
MATCH (w:WatchlistEntry)<-[:LISTED_AS]-(c:Customer)<-[:OWNED_BY]-(a:Account)
MATCH (a)<-[t:TRANSFER]-(s:Account)-[:OWNED_BY]->(o:Customer)
WHERE o.id <> c.id
WITH c.id AS customer_id, c.name AS listed_customer, w.reason AS reason,
     count(DISTINCT o) AS payers, count(t) AS payments,
     round(sum(t.amount_usd)) AS amount_usd
RETURN customer_id, listed_customer, reason, payers, payments, amount_usd
ORDER BY amount_usd DESC, customer_id
LIMIT $limit
""",
    },
    {
        "id": "FN13",
        "title": "Cross-border payment corridors",
        "layer": "both",
        "question": ("Between which pairs of countries does the most money move, "
                     "in dollars at the exchange rate of the month?"),
        "why_graph": ("Payments are in many currencies. Each is priced with the "
                      "real rate for its month, so a corridor's total is "
                      "comparable with every other."),
        "params": {"limit": 10},
        "cypher": """
MATCH (a:Account)-[t:TRANSFER]->(b:Account)
WHERE t.cross_border = true
WITH a.iso3 AS from_country, b.iso3 AS to_country, count(t) AS payments,
     round(sum(t.amount_usd) / 1000.0) AS amount_usd_thousand
RETURN from_country, to_country, payments, amount_usd_thousand
ORDER BY amount_usd_thousand DESC, from_country, to_country
LIMIT $limit
""",
    },
    {
        "id": "FN14",
        "title": "Troubled loans against national bad-loan rates",
        "layer": "both",
        "question": ("In each country, what share of our loans is late or in "
                     "default, beside the World Bank's bad-loan ratio for that "
                     "country's banks?"),
        "why_graph": ("A generated loan book beside a real national benchmark. "
                      "The country node carries the benchmark."),
        "params": {"min_loans": 20, "limit": 10},
        "cypher": """
MATCH (c:Customer)-[:BORROWED]->(l:Loan)
MATCH (c)-[:BASED_IN]->(k:Country)
WHERE k.bank_npl_pct IS NOT NULL
WITH k.name AS country, k.bank_npl_pct AS national_npl_pct,
     k.bank_npl_pct_year AS npl_year, count(l) AS loans,
     sum(CASE WHEN l.status = "late" OR l.status = "defaulted" THEN 1 ELSE 0 END) AS troubled
WHERE loans >= $min_loans
WITH country, national_npl_pct, npl_year, loans,
     round(100.0 * troubled / loans) AS troubled_pct
RETURN country, loans, troubled_pct, national_npl_pct, npl_year
ORDER BY troubled_pct DESC, country
LIMIT $limit
""",
    },
    {
        "id": "FN15",
        "title": "Who is on the hook when a borrower defaults",
        "layer": "synthetic",
        "question": ("For borrowers with a defaulted loan, how many customers "
                     "stand behind them as guarantors, directly or through a chain "
                     "of guarantees?"),
        "why_graph": ("A guarantor may themselves be guaranteed. The chain is "
                      "walked to three steps in one pattern."),
        "params": {"limit": 10},
        "cypher": """
MATCH (b:Customer)-[:BORROWED]->(l:Loan)
WHERE l.status = "defaulted"
MATCH (g:Customer)-[:GUARANTEES*1..3]->(b)
WHERE g.id <> b.id
WITH b.id AS customer_id, b.name AS borrower, count(DISTINCT l) AS defaulted_loans,
     count(DISTINCT g) AS guarantors
RETURN customer_id, borrower, defaulted_loans, guarantors
ORDER BY guarantors DESC, customer_id
LIMIT $limit
""",
    },
    {
        "id": "FN16",
        "title": "How much of this graph is real",
        "layer": "both",
        "question": "How many nodes come from public data and how many are generated?",
        "why_graph": ("Provenance is a property on every node and edge, so the "
                      "split is a query, not a claim in a document."),
        "params": {},
        "cypher": """
MATCH (n)
WITH n.provenance AS provenance, count(n) AS nodes
RETURN provenance, nodes
ORDER BY nodes DESC
""",
    },
]

PLACEHOLDER = re.compile(r"\$([a-z_][a-z0-9_]*)")


def get(query_id: str) -> dict:
    for entry in QUERIES:
        if entry["id"] == query_id:
            return entry
    raise KeyError(f"no query {query_id!r}; known: {[q['id'] for q in QUERIES]}")


def render(entry: dict, **overrides) -> str:
    """The query with its parameters filled in as escaped Cypher literals.

    Unknown overrides are an error, not ignored: a misspelt parameter would
    otherwise run the default and return an answer to a different question.
    """
    unknown = set(overrides) - set(entry["params"])
    if unknown:
        raise KeyError(f"{entry['id']} takes {sorted(entry['params'])}, "
                       f"not {sorted(unknown)}")
    values = {**entry["params"], **overrides}
    for name, default in entry["params"].items():
        if type(values[name]) is not type(default) and not (
                isinstance(default, float) and isinstance(values[name], int)):
            raise TypeError(f"{entry['id']}: {name} must be "
                            f"{type(default).__name__}, got {values[name]!r}")

    def fill(match: re.Match) -> str:
        name = match.group(1)
        if name not in values:
            raise KeyError(f"{entry['id']}: ${name} is used in the query but has "
                           f"no default in `params`")
        return cypher_literal(values[name])

    return PLACEHOLDER.sub(fill, entry["cypher"]).strip()
