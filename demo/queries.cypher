// The ten queries of the demo, in the order it runs them.
// Written by `python -m demo.demo --write-cypher`. Do not edit.

// 1. How much of this graph is real  (FN16, layer: both)
// First, what is this graph made of?
MATCH (n)
WITH n.provenance AS provenance, count(n) AS nodes
RETURN provenance, nodes
ORDER BY nodes DESC;

// 2. Bank failures, year by year  (FN01, layer: real)
// Real data. US bank failures since the financial crisis.
MATCH (f:BankFailure)
WHERE f.year >= 2007 AND f.year <= 2026
WITH f.year AS year, count(f) AS failures,
     round(sum(f.assets_usd) / 1000000000.0) AS assets_usd_billion,
     round(sum(coalesce(f.estimated_loss_usd, 0)) / 1000000000.0) AS loss_usd_billion
RETURN year, failures, assets_usd_billion, loss_usd_billion
ORDER BY year;

// 3. Holding companies that control the most banks  (FN02, layer: real)
// Which holding companies control the most banks?
MATCH (b:Bank)-[:CONTROLLED_BY]->(h:HoldingCompany)
WITH h.name AS holding_company, count(b) AS banks,
     round(sum(b.assets_usd) / 1000000000.0) AS assets_usd_billion
RETURN holding_company, banks, assets_usd_billion
ORDER BY banks DESC, assets_usd_billion DESC, holding_company
LIMIT 10;

// 4. Which countries own the most Indian companies  (FN05, layer: real)
// India. Which countries own the most Indian companies?
MATCH (e:LegalEntity)-[:LOCATED_IN]->(home:Country)
WHERE home.iso3 = "IND"
MATCH (e)-[c:CONSOLIDATED_BY]->(p:LegalEntity)
WHERE c.level = "ultimate"
MATCH (p)-[:LOCATED_IN]->(k:Country)
WHERE k.iso3 <> "IND"
WITH k.name AS parent_country, count(DISTINCT e) AS entities,
     count(DISTINCT p) AS parents
RETURN parent_country, entities, parents
ORDER BY entities DESC, parent_country
LIMIT 10;

// 5. Who ultimately owns an Indian company  (FN04, layer: real)
// One Indian company, and every parent above it.
MATCH (e:LegalEntity)-[:CONSOLIDATED_BY*1..6]->(p:LegalEntity)
WHERE e.lei = "335800DJLEUSVXIZV875"
MATCH (p)-[:LOCATED_IN]->(k:Country)
WITH DISTINCT p.name AS parent, k.name AS country, p.lei AS lei
RETURN parent, country, lei
ORDER BY parent, lei;

// 6. A currency against the dollar  (FN08, layer: real)
// The rupee against the dollar, year end to year end.
MATCH (r:ExchangeRate)-[:RATE_OF]->(c:Currency)
WHERE c.code = "INR" AND r.month_no = 12
WITH r.year AS year, r.date AS rate_date, r.per_usd AS per_usd
RETURN year, rate_date, per_usd
ORDER BY year;

// 7. Money going round in a circle  (FN09, layer: synthetic)
// Now the generated half. Money going round in a circle.
MATCH (a:Account)-[t1:TRANSFER]->(b:Account)-[t2:TRANSFER]->(c:Account)-[t3:TRANSFER]->(a)
WHERE t1.amount_usd >= 15000.0 AND t2.amount_usd >= 15000.0
  AND t3.amount_usd >= 15000.0 AND a.id < b.id AND a.id < c.id
WITH a.account_no AS first, b.account_no AS second, c.account_no AS third,
     round(t1.amount_usd) AS sent_usd, round(t3.amount_usd) AS returned_usd
RETURN first, second, third, sent_usd, returned_usd
ORDER BY sent_usd DESC, first
LIMIT 10;

// 8. Accounts flagged for structuring  (FN10, layer: synthetic)
// Payments kept just under the reporting threshold.
MATCH (al:Alert)-[:FLAGS]->(a:Account)-[:OWNED_BY]->(c:Customer),
      (a)-[:HELD_AT]->(i:Institution)
WHERE al.kind = "structuring"
WITH a.account_no AS account, c.name AS customer, i.name AS institution,
     al.month AS month, al.transfers AS transfers, round(al.amount_usd) AS amount_usd
RETURN account, customer, institution, month, transfers, amount_usd
ORDER BY amount_usd DESC, account
LIMIT 10;

// 9. Who paid a watchlisted customer  (FN12, layer: synthetic)
// Who paid a customer on the watchlist?
MATCH (w:WatchlistEntry)<-[:LISTED_AS]-(c:Customer)<-[:OWNED_BY]-(a:Account)
MATCH (a)<-[t:TRANSFER]-(s:Account)-[:OWNED_BY]->(o:Customer)
WHERE o.id <> c.id
WITH c.id AS customer_id, c.name AS listed_customer, w.reason AS reason,
     count(DISTINCT o) AS payers, count(t) AS payments,
     round(sum(t.amount_usd)) AS amount_usd
RETURN customer_id, listed_customer, reason, payers, payments, amount_usd
ORDER BY amount_usd DESC, customer_id
LIMIT 10;

// 10. Cross-border payment corridors  (FN13, layer: both)
// Cross-border flows, priced at the real exchange rate.
MATCH (a:Account)-[t:TRANSFER]->(b:Account)
WHERE t.cross_border = true
WITH a.iso3 AS from_country, b.iso3 AS to_country, count(t) AS payments,
     round(sum(t.amount_usd) / 1000.0) AS amount_usd_thousand
RETURN from_country, to_country, payments, amount_usd_thousand
ORDER BY amount_usd_thousand DESC, from_country, to_country
LIMIT 10;
