"""Build and load the finance graph into Samyama.

Two habits carried over from interconnect-ip-kg, both learned the hard way:

**It verifies edges, not just nodes.** `create_edges` resolves endpoints with
`MATCH ... WHERE v.id = ...`. If an endpoint is missing the MATCH finds nothing,
the CREATE has no rows to act on, and the statement succeeds having created
nothing. So verification counts every label AND every edge type against what
was sent, and exits non-zero on any mismatch.

**It runs without the engine.** `--dry-run` writes the whole load out as Cypher
and checks it locally.

Usage:
    python -m etl.download_data                 # once, fetches data/raw/
    python -m etl.loader --dry-run              # emit Cypher, no engine needed
    python -m etl.loader --layers real          # public data only
    python -m etl.loader                        # real + generated, embedded engine
    python -m etl.loader --url http://127.0.0.1:8080 --reset
"""
from __future__ import annotations

import sys
import time
from collections import Counter
from pathlib import Path

import click

from etl import download_data, real_layer
from etl import generate as gen
from etl.helpers import (
    GENERATED_SOURCE,
    REAL,
    SYNTHETIC,
    create_edges,
    create_nodes,
    edge_props,
    props_map,
)

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "schema" / "finance_kg.cypher"
DRY_RUN_PATH = ROOT / "data" / "generated" / "load.cypher"
GRAPH = "default"

# Declared here as well as in the schema header, and pinned to it by
# tests/test_docs_match_data.py.
NODE_LABELS = [
    "Country", "Currency", "ExchangeRate", "Exchange", "State", "Industry", "Company",
    "Filing", "Regulator", "HoldingCompany", "Bank", "BankFailure", "LegalEntity",
    "Institution", "Customer", "Account", "Device", "Loan", "WatchlistEntry", "Alert",
]
REAL_LABELS = NODE_LABELS[:13]
SYNTHETIC_LABELS = NODE_LABELS[13:]

# The edges the public sources supply: (edge type, label it leaves from).
# BASED_IN, LOCATED_IN and IN_INDUSTRY are drawn by both layers, so the source
# label is part of the rule.
REAL_EDGES = {
    ("USES", "Country"), ("RATE_OF", "ExchangeRate"), ("LOCATED_IN", "Exchange"),
    ("PART_OF", "State"), ("LISTED_ON", "Company"), ("IN_INDUSTRY", "Company"),
    ("BASED_IN", "Company"), ("FILED_BY", "Filing"), ("SAME_AS", "Company"),
    ("LOCATED_IN", "Bank"), ("SUPERVISED_BY", "Bank"), ("CONTROLLED_BY", "Bank"),
    ("OCCURRED_IN", "BankFailure"), ("FAILURE_OF", "BankFailure"),
    ("LOCATED_IN", "LegalEntity"), ("CONSOLIDATED_BY", "LegalEntity"),
    ("BRANCH_OF", "LegalEntity"),
}
# The only real things a generated edge may point at: reference data that
# names no organisation. See invariant 3.
NEUTRAL_LABELS = {"Country", "Currency", "Industry"}


class MissingData(RuntimeError):
    """data/raw/ is incomplete. Raised rather than loading a partial graph."""


def build(layers: str = "all", seed: int = gen.DEFAULT_SEED, scale: float = 1.0,
          raw_dir: Path = download_data.RAW_DIR):
    """Assemble the graph. `layers` is "real" or "all".

    There is no "synthetic only": the generated layer is placed in real
    countries, in real currencies, at real exchange rates.

    Returns (nodes, edges, dropped) where `dropped` counts the source rows that
    could not be joined and were left out.
    """
    gone = download_data.missing(raw_dir)
    if gone:
        raise MissingData(
            f"{len(gone)} source file(s) missing from {raw_dir}: {', '.join(gone)}. "
            f"Run `python -m etl.download_data`."
        )
    nodes, edges, dropped = real_layer.build(raw_dir)
    if layers == "all":
        more_nodes, more_edges = gen.generate(nodes, edges, seed=seed, scale=scale)
        nodes = nodes + more_nodes
        edges = edges + more_edges
    return nodes, edges, dropped


def check_integrity(nodes: list[dict], edges: list[dict]) -> list[str]:
    """Everything checkable before a single statement is sent."""
    problems: list[str] = []

    ids = Counter(n["id"] for n in nodes)
    problems += [f"duplicate id: {i} appears {c} times" for i, c in ids.items() if c > 1]

    known = set(ids)
    for e in edges:
        for end in ("src", "dst"):
            if e[end] not in known:
                problems.append(
                    f"{e['_type']}: {end} {e[end]!r} matches no node -- this edge "
                    f"would be silently skipped by the engine"
                )
    if problems:
        return problems     # the checks below index by id and need clean ids

    unknown = {n["_label"] for n in nodes} - set(NODE_LABELS)
    if unknown:
        problems.append(f"labels not declared in NODE_LABELS: {sorted(unknown)}")

    # Invariant 1: provenance is present, consistent, and matches the label.
    for n in nodes:
        want = REAL if n["_label"] in REAL_LABELS else SYNTHETIC
        if n.get("provenance") != want:
            problems.append(f"invariant 1: {n['id']} is a {n['_label']} but is "
                            f"stamped {n.get('provenance')!r}, expected {want!r}")
        if (n.get("source") == GENERATED_SOURCE) != (want == SYNTHETIC):
            problems.append(f"invariant 1: {n['id']} has source {n.get('source')!r}")

    # Invariant 2: every edge is stamped, and the stamp is earned. An edge is
    # real only if a public source supplies that kind of edge AND both its ends
    # are real.
    by_id = {n["id"]: n for n in nodes}
    for e in edges:
        src, dst = by_id[e["src"]], by_id[e["dst"]]
        earned = ((e["_type"], src["_label"]) in REAL_EDGES
                  and src["provenance"] == REAL and dst["provenance"] == REAL)
        want = REAL if earned else SYNTHETIC
        if e.get("provenance") != want:
            problems.append(
                f"invariant 2: {e['_type']} {e['src']} -> {e['dst']} is stamped "
                f"{e.get('provenance')!r}, expected {want!r}")

        # Invariant 3: nothing generated is attached to a real organisation.
        # A generated account at a real bank, or a real company on a generated
        # watchlist, would be an invented claim about it.
        if e.get("provenance") == SYNTHETIC:
            for end in (src, dst):
                if end["provenance"] == REAL and end["_label"] not in NEUTRAL_LABELS:
                    problems.append(
                        f"invariant 3: generated edge {e['_type']} touches the real "
                        f"{end['_label']} {end['id']}")

    # Invariant 4: every account has exactly one owner, one institution and
    # one currency.
    links: dict[str, Counter] = {}
    for e in edges:
        if e["_type"] in ("OWNED_BY", "HELD_AT", "DENOMINATED_IN"):
            links.setdefault(e["src"], Counter())[e["_type"]] += 1
    for n in nodes:
        if n["_label"] == "Account":
            got = links.get(n["id"], Counter())
            for kind in ("OWNED_BY", "HELD_AT", "DENOMINATED_IN"):
                if got[kind] != 1:
                    problems.append(f"invariant 4: {n['id']} has {got[kind]} {kind}, "
                                    f"expected 1")

    # Invariant 5: a transfer's dollar value is its amount at the real rate
    # for its month.
    rate = {(n["currency"], n["month"]): n["per_usd"]
            for n in nodes if n["_label"] == "ExchangeRate"}
    for e in edges:
        if e["_type"] != "TRANSFER":
            continue
        known = rate.get((e["currency"], e["month"]))
        if known is None:
            problems.append(f"invariant 5: no {e['currency']} rate for {e['month']}, "
                            f"needed by {e['src']} -> {e['dst']}")
        elif abs(e["amount"] / known - e["amount_usd"]) > 0.011:
            problems.append(
                f"invariant 5: {e['src']} -> {e['dst']} is {e['amount']} "
                f"{e['currency']}, recorded as {e['amount_usd']} USD, but the rate "
                f"for {e['month']} gives {e['amount'] / known:.2f}")

    return problems


class HttpClient:
    """Minimal client over the engine's `POST /api/query`, standard library only.

    Matches SamyamaClient's `.query(stmt, graph)` shape so `create_nodes` and
    `create_edges` work against either without knowing which they have.
    """

    def __init__(self, url: str):
        self.url = url.rstrip("/") + "/api/query"

    class _Result:
        __slots__ = ("records", "columns")

        def __init__(self, payload: dict):
            self.records = payload.get("records") or []
            self.columns = payload.get("columns") or []

    def query(self, statement: str, graph: str = GRAPH):
        import json
        import urllib.error
        import urllib.request

        body = json.dumps({"query": statement, "graph": graph}).encode()
        req = urllib.request.Request(
            self.url, data=body, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                return self._Result(json.loads(resp.read()))
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:400].decode(errors="replace")
            raise RuntimeError(f"HTTP {exc.code}: {detail}\n  {statement[:180]}") from exc


def connect(url: str | None):
    """An HTTP client for a URL, the embedded engine otherwise.

    The embedded engine lives and dies with the process: a graph loaded into it
    is gone when the script exits. It is for the demo, the tests and the MCP
    server, which load and then query in one run. To keep a graph, load it into
    a running server with --url.
    """
    if url:
        return HttpClient(url)
    from samyama import SamyamaClient
    return SamyamaClient.embedded()


def schema_statements() -> list[str]:
    out = []
    for raw in SCHEMA_PATH.read_text(encoding="utf-8").splitlines():
        stmt = raw.split("//", 1)[0].strip().rstrip(";")
        if stmt:
            out.append(stmt)
    return out


def apply_schema(client, graph: str = GRAPH, log=None) -> int:
    applied = 0
    for stmt in schema_statements():
        try:
            client.query(stmt, graph)
            applied += 1
        except Exception as exc:  # already exists, or unsupported syntax
            if log:
                log(f"  ! schema stmt skipped ({exc.__class__.__name__}): {stmt[:60]}")
    return applied


def reset_graph(client, graph: str = GRAPH) -> None:
    client.query("MATCH (n) DETACH DELETE n", graph)


def load(client, nodes: list[dict], edges: list[dict], graph: str = GRAPH,
         log=None) -> None:
    """Send everything. Nodes by label, then edges by type."""
    say = log or (lambda _msg: None)
    by_label: dict[str, list[dict]] = {}
    for n in nodes:
        by_label.setdefault(n["_label"], []).append(n)
    for label in NODE_LABELS:
        rows = by_label.get(label, [])
        if rows:
            create_nodes(client, graph, label, rows)
            say(f"  {label:16} {len(rows):7,}")

    label_of = {n["id"]: n["_label"] for n in nodes}
    by_type: dict[str, list[dict]] = {}
    for e in edges:
        by_type.setdefault(e["_type"], []).append(e)
    for edge_type, rows in sorted(by_type.items()):
        create_edges(client, graph, rows, label_of)
        say(f"  {edge_type:16} {len(rows):7,}")


def scalar(client, statement: str, graph: str = GRAPH):
    return client.query(statement, graph).records[0][0]


def verify(client, nodes: list[dict], edges: list[dict], graph: str = GRAPH) -> list[str]:
    """Count what is in the graph against what was sent. Per label, per type."""
    mismatches: list[str] = []
    sent_nodes = Counter(n["_label"] for n in nodes)
    for label in NODE_LABELS:
        expected = sent_nodes.get(label, 0)
        got = scalar(client, f"MATCH (n:{label}) RETURN count(n) AS n", graph)
        if got != expected:
            mismatches.append(f"{label}: expected {expected}, graph has {got}")

    sent_edges = Counter(e["_type"] for e in edges)
    for edge_type, expected in sorted(sent_edges.items()):
        got = scalar(client, f"MATCH ()-[r:{edge_type}]->() RETURN count(r) AS n", graph)
        if got != expected:
            mismatches.append(
                f"{edge_type}: expected {expected}, graph has {got}"
                + ("  <- endpoints probably missing" if got < expected else "")
            )
    return mismatches


def load_embedded(layers: str = "all", seed: int = gen.DEFAULT_SEED, scale: float = 1.0,
                  raw_dir: Path = download_data.RAW_DIR, log=None):
    """Build, check, load into a fresh embedded engine and verify.

    Returns (client, nodes, edges). Raises on any integrity or count problem:
    callers query the result, and a graph that loaded short would answer every
    question slightly wrong.
    """
    nodes, edges, _ = build(layers, seed, scale, raw_dir)
    problems = check_integrity(nodes, edges)
    if problems:
        raise RuntimeError("integrity check failed: " + "; ".join(problems[:5]))
    client = connect(None)
    apply_schema(client)
    load(client, nodes, edges, log=log)
    mismatches = verify(client, nodes, edges)
    if mismatches:
        raise RuntimeError("load verification failed: " + "; ".join(mismatches))
    return client, nodes, edges


def write_cypher(nodes: list[dict], edges: list[dict], path: Path = DRY_RUN_PATH) -> Path:
    """Emit the whole load as Cypher. No engine required."""
    path.parent.mkdir(parents=True, exist_ok=True)
    label_of = {n["id"]: n["_label"] for n in nodes}
    with path.open("w", encoding="utf-8") as out:
        out.write("// Generated by etl/loader.py --dry-run. Do not edit.\n\n")
        for stmt in schema_statements():
            out.write(stmt + ";\n")
        out.write("\n")
        for n in nodes:
            out.write(f"CREATE (:{n['_label']} {props_map(n)});\n")
        for e in edges:
            props = edge_props(e)
            rel = f"[:{e['_type']}" + (f" {props_map(props)}]" if props else "]")
            out.write(
                f'MATCH (a:{label_of[e["src"]]}), (b:{label_of[e["dst"]]}) '
                f'WHERE a.id = "{e["src"]}" AND b.id = "{e["dst"]}" '
                f"CREATE (a)-{rel}->(b);\n"
            )
    return path


def summarise(nodes: list[dict], edges: list[dict], dropped: dict, echo) -> None:
    real = sum(1 for n in nodes if n["provenance"] == REAL)
    real_edges = sum(1 for e in edges if e["provenance"] == REAL)
    pct = (100 * real / len(nodes)) if nodes else 0
    echo(f"  {len(nodes):,} nodes, {len(edges):,} edges")
    echo(f"  nodes: {real:,} real, {len(nodes) - real:,} synthetic ({pct:.1f}% real)")
    echo(f"  edges: {real_edges:,} real, {len(edges) - real_edges:,} synthetic")
    for reason, count in sorted(dropped.items()):
        echo(f"  left out: {count:,} {reason.replace('_', ' ')}")


@click.command()
@click.option("--url", default=None, help="Samyama URL. Omit for the embedded engine.")
@click.option("--graph", default=GRAPH, show_default=True, help="Graph name.")
@click.option("--layers", type=click.Choice(["real", "all"]), default="all",
              show_default=True, help="`real` loads only the public data.")
@click.option("--seed", type=int, default=gen.DEFAULT_SEED, show_default=True)
@click.option("--scale", type=float, default=1.0, show_default=True,
              help="Multiplier on generated companies and purchase orders.")
@click.option("--reset", is_flag=True, help="Delete everything in the graph first.")
@click.option("--dry-run", is_flag=True, help="Emit Cypher and check it. No engine.")
def main(url, graph, layers, seed, scale, reset, dry_run):
    click.echo(f"[build] layers={layers} seed={seed} scale={scale}")
    try:
        nodes, edges, dropped = build(layers, seed, scale)
    except MissingData as exc:
        click.echo(f"  ! {exc}", err=True)
        sys.exit(1)
    summarise(nodes, edges, dropped, click.echo)

    click.echo("[check] pre-load integrity")
    problems = check_integrity(nodes, edges)
    if problems:
        for p in problems[:20]:
            click.echo(f"  ! {p}", err=True)
        if len(problems) > 20:
            click.echo(f"  ! ... and {len(problems) - 20} more", err=True)
        click.echo("  refusing to load a graph that is already known to be wrong", err=True)
        sys.exit(1)
    click.echo("  ok")

    if dry_run:
        out = write_cypher(nodes, edges)
        click.echo(f"[dry-run] wrote {out} ({out.stat().st_size // 1024:,} KB)")
        click.echo("  no engine used; nothing was loaded")
        return

    click.echo("[connect] " + (url or "embedded engine"))
    try:
        client = connect(url)
    except Exception as exc:
        click.echo(f"  ! could not connect: {exc}", err=True)
        click.echo("  try --dry-run, which needs no engine", err=True)
        sys.exit(1)

    if reset:
        click.echo("[reset] deleting existing graph contents")
        reset_graph(client, graph)

    click.echo(f"[schema] {apply_schema(client, graph, click.echo)} statements applied")
    click.echo("[load]")
    started = time.time()
    load(client, nodes, edges, graph, click.echo)
    click.echo(f"  loaded in {time.time() - started:.1f}s")

    click.echo("[verify] counting the graph against what was sent")
    mismatches = verify(client, nodes, edges, graph)
    if mismatches:
        for m in mismatches:
            click.echo(f"  ! {m}", err=True)
        sys.exit(1)
    click.echo(f"  ok -- {len(nodes):,} nodes and {len(edges):,} edges, every label "
               f"and every edge type accounted for")
    if not url:
        click.echo("  note: the embedded engine is in-process; this graph is gone "
                   "when the command exits. Use --url to keep one.")


if __name__ == "__main__":
    main()
