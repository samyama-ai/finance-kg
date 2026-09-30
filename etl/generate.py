"""The generated layer: the banking activity nobody publishes.

Customers, accounts, payments, loans, devices, watchlists and alerts. None of
it is public, anywhere, for good reason. So it is GENERATED, deterministically
from a seed, and every node and edge built here is stamped
`provenance: synthetic`.

WHAT THIS LAYER DEMONSTRATES, IT DOES NOT REPORT. A query over it shows the
kind of question the graph answers. Its numbers say nothing about any real
person, company, bank or payment.

Two rules shape everything below.

**Nothing generated is attached to a real organisation.** This layer has its
own institutions and its own customers, with coined names. It never opens an
account at a bank the real layer names, never makes a real company a customer,
and never puts a real name on a watchlist. A generated fraud ring at a real
bank would be an invented allegation about it. The two layers meet only at
neutral reference data: countries, currencies, exchange rates and industries.
`etl/loader.check_integrity` enforces this.

**Totals are counted, not drawn.** Alerts are raised by applying a rule to the
generated transfers, not generated beside them, and every transfer's dollar
value is its amount converted at the REAL exchange rate for its month.

The patterns a fraud team looks for are planted on purpose -- rings, payments
structured to stay under a reporting threshold, accounts that collect and
forward -- and each planted transfer records which pattern it belongs to, so a
detection query can be scored against the truth.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta

from etl.helpers import GENERATED_SOURCE, SYNTHETIC, edge, node, rid, seeded, weighted_pick

DEFAULT_SEED = 20260929

# The generated world runs from WINDOW_START to AS_OF. AS_OF is a constant, not
# today's date: the same seed must give the same graph next month.
WINDOW_START = date(2024, 1, 1)
AS_OF = date(2026, 8, 31)

INSTITUTIONS = 40
CUSTOMERS = 3000
LOANS = 1200
BACKGROUND_TRANSFERS = 36000
RINGS = 25
STRUCTURED_ACCOUNTS = 30
MULE_ACCOUNTS = 20
WATCHLIST_ENTRIES = 60
LISTED_CUSTOMERS = 40
WATCHLIST_NAME = "Scenario watchlist"

# The rule that raises a structuring alert. Transfers just under a reporting
# threshold, several of them, into one account, in one calendar month.
THRESHOLD_USD = 10000.0
STRUCTURING_FLOOR_USD = 9000.0
STRUCTURING_MINIMUM = 5

NAME_HEAD = ["Zor", "Vel", "Kes", "Nor", "Hal", "Mer", "Tes", "Bral", "Quen", "Dov",
             "Ulm", "Pryn", "Sav", "Tarn", "Ost", "Yar", "Cald", "Fen", "Gry", "Ith",
             "Jor", "Lum", "Mav", "Nyx", "Orv", "Pell", "Rho", "Syl", "Thal", "Vos"]
NAME_TAIL = ["vane", "dris", "mont", "lane", "quist", "ford", "wick", "holm", "tera",
             "vik", "stan", "rell", "gate", "mere", "loft", "brae", "dale", "nor",
             "sund", "port", "hurst", "well", "crest", "field"]
GIVEN_HEAD = ["Ta", "Mi", "Ro", "Se", "Ka", "Li", "Jo", "Na", "Pe", "Vi", "Da", "El",
              "Fa", "Ga", "Ha", "Is"]
GIVEN_TAIL = ["vin", "rel", "nna", "dor", "lis", "mek", "rah", "sol", "tia", "von",
              "wen", "zar"]
BUSINESS_SUFFIX = ["Trading", "Holdings", "Industries", "Services", "Supply", "Works",
                   "Logistics", "Foods", "Textiles", "Systems"]
INSTITUTION_SUFFIX = {"retail": ["Savings Bank", "Community Bank", "Peoples Bank"],
                      "commercial": ["Commercial Bank", "Merchant Bank"],
                      "digital": ["Digital Bank", "Payments"]}
CHANNELS = ["wire", "instant", "card", "cheque"]


def month_of(day: date) -> str:
    return day.strftime("%Y-%m")


class World:
    """The parts of the real layer the generator reads. Nothing here is written."""

    def __init__(self, real_nodes: list[dict], real_edges: list[dict]):
        by_label: dict[str, list[dict]] = defaultdict(list)
        for n in real_nodes:
            by_label[n["_label"]].append(n)
        self.industries = sorted(n["id"] for n in by_label["Industry"])

        # currency -> month -> units of that currency per US dollar
        self.per_usd: dict[str, dict[str, float]] = defaultdict(dict)
        for n in by_label["ExchangeRate"]:
            self.per_usd[n["currency"]][n["month"]] = n["per_usd"]
        self.months = sorted(self.per_usd.get("USD", {}))
        if not self.months:
            raise ValueError("the real layer holds no US dollar exchange rates")

        uses: dict[str, list[str]] = defaultdict(list)
        for e in real_edges:
            if e["_type"] == "USES":
                uses[e["src"]].append(e["dst"].split(":")[1])
        # Only a currency with a published rate for EVERY month of the window
        # can be used: a transfer with no rate has no dollar value. The rouble,
        # which the ECB stopped quoting in 2022, is one that drops out.
        window = [m for m in self.months
                  if month_of(WINDOW_START) <= m <= month_of(AS_OF)]
        complete = {code for code, rates in self.per_usd.items()
                    if all(m in rates for m in window)}
        self.currency_of: dict[str, str] = {}
        self.weight: dict[str, float] = {}
        for n in sorted(by_label["Country"], key=lambda c: c["id"]):
            rated = sorted(c for c in uses[n["id"]] if c in complete)
            if not rated or not n.get("gdp_usd"):
                continue
            self.currency_of[n["iso3"]] = rated[0]
            # The square root, or a quarter of all customers would be American.
            self.weight[n["iso3"]] = math.sqrt(n["gdp_usd"])
        if len(self.currency_of) < 2:
            raise ValueError("fewer than two countries have both a GDP and a rated currency")

    def rate(self, currency: str, day: date) -> float:
        """Units of the currency per US dollar, at the month-end rate for `day`.

        Where a currency has no rate for the month, the latest earlier one is
        used, and failing that the earliest it has.
        """
        month = min(max(month_of(day), self.months[0]), self.months[-1])
        rates = self.per_usd[currency]
        if month in rates:
            return rates[month]
        earlier = [m for m in rates if m <= month]
        return rates[max(earlier)] if earlier else rates[min(rates)]

    def to_usd(self, amount: float, currency: str, day: date) -> float:
        return round(amount / self.rate(currency, day), 2)

    def from_usd(self, usd: float, currency: str, day: date) -> float:
        return round(usd * self.rate(currency, day), 2)


def generate(real_nodes: list[dict], real_edges: list[dict],
             seed: int = DEFAULT_SEED, scale: float = 1.0):
    """Returns (nodes, edges), every one of them stamped synthetic."""
    rng = seeded(seed)
    world = World(real_nodes, real_edges)
    nodes: list[dict] = []
    edges: list[dict] = []

    def scaled(count: int, floor: int) -> int:
        return max(floor, round(count * scale))

    def make(label: str, node_id: str, **props) -> dict:
        built = node(label, node_id, SYNTHETIC, GENERATED_SOURCE, **props)
        nodes.append(built)
        return built

    def link(edge_type: str, src: str, dst: str, **props) -> None:
        edges.append(edge(edge_type, src, dst, SYNTHETIC, **props))

    countries = sorted(world.weight)
    weights = [world.weight[c] for c in countries]
    used_names: set[str] = set()

    def coin(parts_a: list[str], parts_b: list[str], suffixes: list[str]) -> str:
        for _ in range(500):
            name = f"{rng.choice(parts_a)}{rng.choice(parts_b)} {rng.choice(suffixes)}"
            if name not in used_names:
                used_names.add(name)
                return name
        raise RuntimeError("ran out of distinct coined names; add syllables")

    span = (AS_OF - WINDOW_START).days

    def any_day() -> date:
        return WINDOW_START + timedelta(days=rng.randint(0, span))

    # ---- institutions ---------------------------------------------------
    institutions: dict[str, list[dict]] = defaultdict(list)     # iso3 -> institutions
    for number in range(1, scaled(INSTITUTIONS, 6) + 1):
        kind = rng.choice(["retail", "retail", "commercial", "digital"])
        iso3 = weighted_pick(rng, countries, weights)
        built = make("Institution", rid("institution", number, 4),
                     name=coin(NAME_HEAD, NAME_TAIL, INSTITUTION_SUFFIX[kind]),
                     kind=kind, iso3=iso3, founded=rng.randint(1948, 2021))
        institutions[iso3].append(built)
        link("BASED_IN", built["id"], f"country:{iso3}")
    everywhere = sorted((i for group in institutions.values() for i in group),
                        key=lambda i: i["id"])

    # ---- customers ------------------------------------------------------
    customers = []
    family = [f"{a}{b}" for a in NAME_HEAD for b in NAME_TAIL]
    for number in range(1, scaled(CUSTOMERS, 60) + 1):
        business = rng.random() < 0.2
        iso3 = weighted_pick(rng, countries, weights)
        if business:
            name = coin(NAME_HEAD, NAME_TAIL, BUSINESS_SUFFIX)
        else:
            name = f"{rng.choice(GIVEN_HEAD)}{rng.choice(GIVEN_TAIL)} {rng.choice(family)}"
        built = make("Customer", rid("customer", number, 6), name=name,
                     kind="business" if business else "person", iso3=iso3,
                     onboarded=any_day().isoformat(),
                     kyc_status=rng.choice(["verified"] * 8 + ["pending", "expired"]),
                     risk_rating=rng.choice(["low"] * 6 + ["medium"] * 3 + ["high"]))
        customers.append(built)
        link("BASED_IN", built["id"], f"country:{iso3}")
        if business:
            link("IN_INDUSTRY", built["id"], rng.choice(world.industries))

    # ---- accounts -------------------------------------------------------
    accounts = []
    owner_of: dict[str, dict] = {}
    for customer in customers:
        for _ in range(rng.choice([1, 1, 2, 2, 3])):
            local = institutions.get(customer["iso3"])
            institution = rng.choice(local) if local else rng.choice(everywhere)
            currency = world.currency_of[customer["iso3"]]
            opened = any_day()
            built = make(
                "Account", rid("account", len(accounts) + 1, 6),
                account_no=f"AC-{len(accounts) + 1:07d}",
                kind=("business" if customer["kind"] == "business"
                      else rng.choice(["current", "current", "savings"])),
                currency=currency, iso3=customer["iso3"], opened=opened.isoformat(),
                status=rng.choice(["active"] * 18 + ["frozen", "closed"]),
                balance=round(rng.lognormvariate(8.2, 1.3), 2))
            accounts.append(built)
            owner_of[built["id"]] = customer
            link("OWNED_BY", built["id"], customer["id"])
            link("HELD_AT", built["id"], institution["id"])
            link("DENOMINATED_IN", built["id"], f"currency:{currency}")

    # ---- devices --------------------------------------------------------
    # An account signs in from a device or two of its own. Sharing a device
    # with another customer's account is therefore unusual, which is what
    # makes it worth looking for: the planted rings and mules do it.
    devices: list[dict] = []
    sign_ins: set[tuple[str, str]] = set()

    def new_device() -> dict:
        built = make("Device", rid("device", len(devices) + 1, 6),
                     kind=rng.choice(["phone", "phone", "laptop", "tablet", "desktop"]),
                     first_seen=any_day().isoformat())
        devices.append(built)
        return built

    def sign_in(account: dict, device: dict) -> None:
        if (account["id"], device["id"]) not in sign_ins:
            sign_ins.add((account["id"], device["id"]))
            link("SIGNED_IN_FROM", account["id"], device["id"])

    own_device: dict[str, dict] = {}
    for account in accounts:
        owner = owner_of[account["id"]]["id"]
        # A customer's accounts share that customer's device.
        if owner not in own_device or rng.random() < 0.25:
            own_device[owner] = new_device()
        sign_in(account, own_device[owner])

    # ---- transfers ------------------------------------------------------
    transfers: list[dict] = []

    def transfer(src: dict, dst: dict, usd: float, day: date, pattern: str) -> None:
        day = min(day, AS_OF)
        amount = world.from_usd(usd, src["currency"], day)
        built = {
            "amount": amount, "currency": src["currency"],
            "amount_usd": world.to_usd(amount, src["currency"], day),
            "date": day.isoformat(), "month": month_of(day),
            "channel": rng.choice(CHANNELS),
            "cross_border": src["iso3"] != dst["iso3"], "pattern": pattern,
        }
        transfers.append({"src": src["id"], "dst": dst["id"], **built})
        link("TRANSFER", src["id"], dst["id"], **built)

    for _ in range(scaled(BACKGROUND_TRANSFERS, 400)):
        src, dst = rng.sample(accounts, k=2)
        transfer(src, dst, round(rng.lognormvariate(6.4, 1.5), 2), any_day(), "background")

    free = rng.sample(accounts, k=len(accounts))      # a shuffled pool, drawn from the end

    # Rings: money goes round a circle of accounts in a few days, a little
    # smaller at each step, and the accounts share one device.
    for _ in range(scaled(RINGS, 3)):
        ring = [free.pop() for _ in range(rng.randint(3, 6))]
        shared = new_device()
        usd = rng.uniform(20000, 90000)
        day = any_day()
        for index, account in enumerate(ring):
            sign_in(account, shared)
            transfer(account, ring[(index + 1) % len(ring)], round(usd, 2), day, "ring")
            usd *= rng.uniform(0.95, 0.99)
            day += timedelta(days=rng.randint(0, 2))

    # Structuring: many payments, each just under the reporting threshold.
    for _ in range(scaled(STRUCTURED_ACCOUNTS, 3)):
        target = free.pop()
        sources = [free.pop() for _ in range(rng.randint(2, 4))]
        first = any_day().replace(day=1)
        for _ in range(rng.randint(STRUCTURING_MINIMUM + 3, 15)):
            usd = round(rng.uniform(STRUCTURING_FLOOR_USD + 100, THRESHOLD_USD - 100), 2)
            transfer(rng.choice(sources), target, usd,
                     first + timedelta(days=rng.randint(0, 26)), "structuring")

    # Mules: an account that collects from many and forwards to one.
    for _ in range(scaled(MULE_ACCOUNTS, 2)):
        mule, sink = free.pop(), free.pop()
        shared = new_device()
        sign_in(mule, shared)
        sign_in(sink, shared)
        day = any_day()
        total = 0.0
        for _ in range(rng.randint(8, 14)):
            usd = round(rng.uniform(800, 4000), 2)
            total += usd
            transfer(free.pop(), mule, usd, day + timedelta(days=rng.randint(0, 3)), "mule")
        transfer(mule, sink, round(total * 0.97, 2), day + timedelta(days=4), "mule")

    # ---- loans and guarantees ------------------------------------------
    for number in range(1, scaled(LOANS, 30) + 1):
        account = rng.choice(accounts)
        borrower = owner_of[account["id"]]
        issued = any_day()
        loan = make("Loan", rid("loan", number, 5),
                    principal=float(rng.choice([5000, 10000, 25000, 50000, 120000,
                                                400000])),
                    currency=account["currency"], rate_pct=round(rng.uniform(4.5, 19.0), 2),
                    term_months=rng.choice([12, 24, 36, 60, 120]),
                    issued=issued.isoformat(),
                    status=rng.choice(["current"] * 12 + ["late"] * 3
                                      + ["defaulted"] * 2 + ["repaid"] * 3))
        loan["principal_usd"] = world.to_usd(loan["principal"], loan["currency"], issued)
        link("BORROWED", borrower["id"], loan["id"])
        link("DISBURSED_TO", loan["id"], account["id"])
        local = institutions.get(borrower["iso3"])
        link("ISSUED_BY", loan["id"], (rng.choice(local) if local
                                       else rng.choice(everywhere))["id"])

    guaranteed: set[tuple[str, str]] = set()
    for _ in range(scaled(CUSTOMERS // 5, 20)):
        guarantor, other = rng.sample(customers, k=2)
        if (guarantor["id"], other["id"]) not in guaranteed:
            guaranteed.add((guarantor["id"], other["id"]))
            link("GUARANTEES", guarantor["id"], other["id"],
                 since=any_day().isoformat())

    # ---- watchlist ------------------------------------------------------
    listed = rng.sample(customers, k=min(scaled(LISTED_CUSTOMERS, 4), len(customers)))
    for number in range(1, scaled(WATCHLIST_ENTRIES, 6) + 1):
        subject = listed[number - 1] if number <= len(listed) else None
        entry = make("WatchlistEntry", rid("watchlist", number, 4),
                     name=(subject["name"] if subject
                           else coin(NAME_HEAD, NAME_TAIL, BUSINESS_SUFFIX)),
                     list_name=WATCHLIST_NAME,
                     reason=rng.choice(["fraud", "sanctions scenario",
                                        "adverse media scenario"]),
                     listed=any_day().isoformat())
        if subject:
            link("LISTED_AS", subject["id"], entry["id"])

    # ---- alerts, raised by rule ----------------------------------------
    raise_alerts(rng, transfers, make, link)
    return nodes, edges


def structuring_hits(transfers: list[dict]) -> dict[tuple[str, str], list[dict]]:
    """(account, month) -> the transfers that trip the structuring rule there.

    The rule, not the planting, decides. A background transfer that happens to
    fall just under the threshold counts, and a planted one over it would not.
    """
    near: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for t in transfers:
        if STRUCTURING_FLOOR_USD <= t["amount_usd"] < THRESHOLD_USD:
            near[(t["dst"], t["month"])].append(t)
    return {key: found for key, found in near.items()
            if len(found) >= STRUCTURING_MINIMUM}


def raise_alerts(rng, transfers: list[dict], make, link) -> None:
    for number, ((account_id, month), found) in enumerate(
            sorted(structuring_hits(transfers).items()), start=1):
        alert = make("Alert", rid("alert", number, 5), kind="structuring", month=month,
                     raised=max(t["date"] for t in found), transfers=len(found),
                     amount_usd=round(sum(t["amount_usd"] for t in found), 2),
                     status=rng.choice(["open", "open", "escalated", "closed"]))
        link("FLAGS", alert["id"], account_id)
