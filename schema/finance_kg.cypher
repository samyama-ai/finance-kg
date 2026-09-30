// Finance Knowledge Graph -- schema
//
// Two layers in one graph, told apart by a property on every node AND edge:
//   provenance: "real"       from a public source
//   provenance: "synthetic"  generated from a seed
// Every node also carries `source`: the dataset's URL, or "generated".
//
// The real layer is organisations and reference data. The generated layer is
// banking activity: customers, accounts, payments, loans. Nothing generated is
// attached to a real organisation.
//
// Node labels (20): Country, Currency, ExchangeRate, Exchange, State, Industry,
//   Company, Filing, Regulator, HoldingCompany, Bank, BankFailure, LegalEntity,
//   Institution, Customer, Account, Device, Loan, WatchlistEntry, Alert
//
// Edge types (26): USES, RATE_OF, LOCATED_IN, PART_OF, LISTED_ON, IN_INDUSTRY,
//   BASED_IN, FILED_BY, SAME_AS, SUPERVISED_BY, CONTROLLED_BY, OCCURRED_IN,
//   FAILURE_OF, CONSOLIDATED_BY, BRANCH_OF, OWNED_BY, HELD_AT,
//   DENOMINATED_IN, SIGNED_IN_FROM, TRANSFER, BORROWED, DISBURSED_TO,
//   ISSUED_BY, GUARANTEES, LISTED_AS, FLAGS
//

// --- Indexes -------------------------------------------------------------
// One on `id` per label: the loader resolves every edge endpoint by id, and an
// unindexed label turns each lookup into a scan. Uniqueness of `id` is a
// LOADER invariant (etl/loader.check_integrity), not a database one.

CREATE INDEX ON :Country(id);
CREATE INDEX ON :Currency(id);
CREATE INDEX ON :ExchangeRate(id);
CREATE INDEX ON :Exchange(id);
CREATE INDEX ON :State(id);
CREATE INDEX ON :Industry(id);
CREATE INDEX ON :Company(id);
CREATE INDEX ON :Filing(id);
CREATE INDEX ON :Regulator(id);
CREATE INDEX ON :HoldingCompany(id);
CREATE INDEX ON :Bank(id);
CREATE INDEX ON :BankFailure(id);
CREATE INDEX ON :LegalEntity(id);
CREATE INDEX ON :Institution(id);
CREATE INDEX ON :Customer(id);
CREATE INDEX ON :Account(id);
CREATE INDEX ON :Device(id);
CREATE INDEX ON :Loan(id);
CREATE INDEX ON :WatchlistEntry(id);
CREATE INDEX ON :Alert(id);

// Lookups the query catalog anchors on.
CREATE INDEX ON :Country(iso3);
CREATE INDEX ON :Currency(code);
CREATE INDEX ON :Company(ticker);
CREATE INDEX ON :LegalEntity(name);
CREATE INDEX ON :Account(account_no);

// --- Real edges: relationship shapes --------------------------------------
// (:Country)-[:USES]->(:Currency)
// (:ExchangeRate)-[:RATE_OF]->(:Currency)
// (:Exchange)-[:LOCATED_IN]->(:Country)
// (:State)-[:PART_OF]->(:Country)
// (:Company)-[:LISTED_ON {ticker}]->(:Exchange)
// (:Company)-[:IN_INDUSTRY]->(:Industry)
// (:Company)-[:BASED_IN]->(:Country)
// (:Filing)-[:FILED_BY]->(:Company)
// (:Company)-[:SAME_AS]->(:LegalEntity)
// (:Bank)-[:LOCATED_IN]->(:State)
// (:Bank)-[:SUPERVISED_BY]->(:Regulator)
// (:Bank)-[:CONTROLLED_BY]->(:HoldingCompany)
// (:BankFailure)-[:OCCURRED_IN]->(:State)
// (:BankFailure)-[:FAILURE_OF]->(:Bank)
// (:LegalEntity)-[:LOCATED_IN]->(:Country)
// (:LegalEntity)-[:CONSOLIDATED_BY {level, since}]->(:LegalEntity)
// (:LegalEntity)-[:BRANCH_OF {since}]->(:LegalEntity)

// --- Generated edges: relationship shapes ---------------------------------
// (:Institution)-[:BASED_IN]->(:Country)
// (:Customer)-[:BASED_IN]->(:Country)
// (:Customer)-[:IN_INDUSTRY]->(:Industry)
// (:Account)-[:OWNED_BY]->(:Customer)
// (:Account)-[:HELD_AT]->(:Institution)
// (:Account)-[:DENOMINATED_IN]->(:Currency)
// (:Account)-[:SIGNED_IN_FROM]->(:Device)
// (:Account)-[:TRANSFER {amount, currency, amount_usd, date, month, channel, cross_border, pattern}]->(:Account)
// (:Customer)-[:BORROWED]->(:Loan)
// (:Loan)-[:DISBURSED_TO]->(:Account)
// (:Loan)-[:ISSUED_BY]->(:Institution)
// (:Customer)-[:GUARANTEES {since}]->(:Customer)
// (:Customer)-[:LISTED_AS]->(:WatchlistEntry)
// (:Alert)-[:FLAGS]->(:Account)

// --- Invariants, enforced by etl/loader.check_integrity -------------------
// 1. Every node has `provenance` and `source`. A real node never has
//    source "generated"; a synthetic node always does.
// 2. Every edge has `provenance`, and the stamp is earned: an edge is real
//    only if it is one of the real shapes above AND both its ends are real.
// 3. Nothing generated is attached to a real organisation. A generated edge
//    may touch a real Country, Currency or Industry, and no other real node.
//    No generated account is held at a real bank, and no real company is a
//    generated customer or appears on a generated watchlist.
// 4. Every account has exactly one owner, one institution and one currency.
// 5. A transfer's dollar value is its amount converted at the real exchange
//    rate for its month.
