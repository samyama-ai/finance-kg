"""Narrated terminal demo: a finance knowledge graph on Samyama.

    python -m demo.demo                  # embedded engine, quick subset
    python -m demo.demo --scale 1.0      # embedded engine, the full graph
    python -m demo.demo --url http://127.0.0.1:8080
    python -m demo.demo --no-pause       # no pacing, for a log or a test
    python -m demo.demo --long           # long form: one tall report, for the GIF
    python -m demo.demo --slides         # one query per screen
    python -m demo.demo --write-cypher   # write the ten queries to demo/queries.cypher

Walks two halves of one graph. First the real half: bank failures, who
controls the banks, who owns Indian companies. Then the generated half: money
moving in circles, payments kept under a reporting threshold, and who paid a
customer on a watchlist.

EVERY NUMBER HERE IS READ FROM THE GRAPH AT RUN TIME. Nothing is typed in, so
the demo cannot claim something the graph no longer contains. Each step is
labelled with the layer its answer rests on, because a viewer must be able to
tell a finding about the world from an illustration.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import click
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from benchmarks.queries import get, render
from etl import generate as gen
from etl import loader

DEFAULT_SCALE = 0.2
CYPHER_PATH = Path(__file__).resolve().parent / "queries.cypher"
# In slide mode a query is shown in at most this many lines. The full text is
# in demo/queries.cypher; the ellipsis says there is more, so the screen never
# shows a shorter query than the one that ran.
SLIDE_CYPHER_LINES = 4
LAYER_STYLE = {
    "real": ("REAL", "green", "public data"),
    "synthetic": ("GENERATED", "yellow", "invented data; no real person or company"),
    "both": ("GENERATED, PRICED WITH REAL DATA", "cyan",
             "invented activity, measured against real reference data"),
}

# (query id, what to say before it, rows to show)
STORY = [
    ("FN16", "First, what is this graph made of?", 5),
    ("FN01", "Real data. US bank failures since the financial crisis.", 12),
    ("FN02", "Which holding companies control the most banks?", 8),
    ("FN05", "India. Which countries own the most Indian companies?", 8),
    ("FN04", "One Indian company, and every parent above it.", 8),
    ("FN08", "The rupee against the dollar, year end to year end.", 8),
    ("FN09", "Now the generated half. Money going round in a circle.", 6),
    ("FN10", "Payments kept just under the reporting threshold.", 6),
    ("FN12", "Who paid a customer on the watchlist?", 6),
    ("FN13", "Cross-border flows, priced at the real exchange rate.", 8),
]


def cell(value, column: str = "") -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        # One decimal at least, two at most: 4.0 and 4.3 line up, 17.57 keeps both.
        text = f"{value:,.2f}".rstrip("0")
        return text + "0" if text.endswith(".") else text
    if isinstance(value, int):
        # A year shown as "2,024" reads as a fault.
        return str(value) if column.endswith("year") else f"{value:,}"
    return str(value)


# --------------------------------------------------------------------------
# Long form. The layout of samyama-graph/case_studies/_lib/demo_lib.py, so this
# recording reads like the other case studies: a title card, a numbered rule
# per step, the query on one line, a plain table, a closing panel. The whole
# report stays on one tall screen with nothing scrolling off.
#
# One thing is added to that layout: the tag after each title saying whether
# the answer is real or generated. Most of this graph is generated, and a
# viewer of a looping GIF has no other way to tell.
# --------------------------------------------------------------------------
LONG_TAG = {
    "real": "[green]real data[/green]",
    "synthetic": "[yellow]generated data[/yellow]",
    "both": "[cyan]real and generated together[/cyan]",
}
SOURCES_LINE = ("data: SEC \u00b7 FDIC \u00b7 GLEIF \u00b7 ECB \u00b7 World Bank (CC BY 4.0) "
                "\u00b7 Wikidata")
TAKEAWAY = ("Bank failures, ownership chains, payment rings, watchlist exposure \u2014\n"
            "all answered as graph traversals. Real organisations and generated "
            "banking activity,\nnever joined to each other.")


def long_pause(seconds: float, enabled: bool) -> None:
    """DEMO_PACE tunes the recording's cadence without an edit, as in demo_lib."""
    if enabled:
        time.sleep(seconds * float(os.environ.get("DEMO_PACE", "1.0")))


def count(client, graph_name: str, pattern: str) -> int:
    return client.query(f"MATCH {pattern} RETURN count(*)", graph_name).records[0][0]


def run_long(console: Console, client, graph_name: str, paced: bool) -> list[str]:
    nodes = count(client, graph_name, "(n)")
    edges = count(client, graph_name, "()-[r]->()")
    companies = count(client, graph_name, "(n:Company)")
    banks = count(client, graph_name, "(n:Bank)")
    entities = count(client, graph_name, "(n:LegalEntity)")
    transfers = count(client, graph_name, "()-[r:TRANSFER]->()")

    console.print(Panel.fit(
        "[bold]Samyama \u00b7 Finance Knowledge Graph[/bold]\n"
        f"{companies:,} companies \u00b7 {banks:,} banks \u00b7 {entities:,} legal "
        f"entities \u00b7 {transfers:,} generated payments\n"
        f"[dim]{SOURCES_LINE}[/dim]",
        border_style="cyan"))
    long_pause(1.4, paced)

    console.print()
    console.rule("[bold cyan]1 \u00b7 Graph loaded into Samyama")
    long_pause(0.5, paced)
    console.print(f"  [green]loaded[/green] [bold]{nodes:,}[/bold] nodes \u00b7 "
                  f"[bold]{edges:,}[/bold] edges")
    long_pause(1.3, paced)

    empty = []
    for index, (query_id, lead, rows) in enumerate(STORY, start=1):
        entry = get(query_id)
        console.print()
        console.rule(f"[bold cyan]{index + 1} \u00b7 {entry['title']}")
        long_pause(0.5, paced)
        console.print(f"  [dim]Q{index}.[/dim] [bold white]{entry['title']}[/bold white]"
                      f"  [dim]\u00b7[/dim] {LONG_TAG[entry['layer']]}")
        console.print(f"       [italic dim]{lead}[/italic dim]")
        statement = render(entry)
        console.print(f"  [dim]cypher>[/dim] [yellow]{escape(' '.join(statement.split()))}"
                      f"[/yellow]")

        began = time.perf_counter()
        result = client.query(statement, graph_name)
        took = 1000 * (time.perf_counter() - began)

        table = Table(show_edge=False, pad_edge=False, box=None,
                      header_style="bold magenta")
        for column in result.columns:
            table.add_column(str(column))
        for row in result.records[:rows]:
            table.add_row(*(cell(v, c) for v, c in zip(row, result.columns, strict=True)))
        console.print(table)
        console.print(f"  [green]\u2192[/green] {len(result.records)} row(s) in "
                      f"[bold]{took:.1f} ms[/bold]")
        long_pause(3.2, paced)
        if not result.records:
            empty.append(query_id)

    console.print()
    console.print(Panel.fit(f"[bold green]{TAKEAWAY}[/bold green]", border_style="green"))
    console.print("  [dim]Customers, institutions and payments are generated. No real "
                  "person or company is among them.[/dim]")
    long_pause(1.6, paced)
    return empty


def shown_cypher(statement: str, slides: bool) -> str:
    lines = statement.splitlines()
    if not slides or len(lines) <= SLIDE_CYPHER_LINES:
        return statement
    return "\n".join(lines[:SLIDE_CYPHER_LINES - 1] + ["\u2026"])


def show(console: Console, client, graph_name: str, step: int, query_id: str, lead: str,
         rows: int, pause, slides: bool) -> int:
    entry = get(query_id)
    tag, colour, meaning = LAYER_STYLE[entry["layer"]]
    if slides:
        console.clear()
    console.rule(f"[bold]{step}/{len(STORY)}  {entry['title']}[/bold]")
    console.print(f"{lead}")
    console.print(f"[{colour}]\\[{tag}][/{colour}] [dim]{meaning}[/dim]\n")
    statement = render(entry)
    console.print(shown_cypher(statement, slides) + "\n", style="dim", highlight=False,
                  markup=False)
    pause(1.5)

    began = time.perf_counter()
    result = client.query(statement, graph_name)
    took = 1000 * (time.perf_counter() - began)

    table = Table(show_edge=False, header_style="bold")
    for column, sample in zip(result.columns, (result.records or [[]])[0], strict=False):
        numeric = isinstance(sample, (int, float)) and not isinstance(sample, bool)
        table.add_column(column, justify="right" if numeric else "left")
    for row in result.records[:rows]:
        table.add_row(*(cell(v, c) for v, c in zip(row, result.columns, strict=True)))
    console.print(table)
    more = len(result.records) - rows
    note = f"  and {more} more" if more > 0 else ""
    console.print(f"[dim]{len(result.records)} rows in {took:.0f} ms{note}[/dim]\n")
    pause(4.0)
    return len(result.records)


def write_cypher(path: Path = CYPHER_PATH) -> Path:
    """The ten queries in full, in the order the demo runs them."""
    lines = ["// The ten queries of the demo, in the order it runs them.",
             "// Written by `python -m demo.demo --write-cypher`. Do not edit.", ""]
    for step, (query_id, lead, _rows) in enumerate(STORY, start=1):
        entry = get(query_id)
        lines += [f"// {step}. {entry['title']}  ({query_id}, layer: {entry['layer']})",
                  f"// {lead}", render(entry) + ";", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


@click.command()
@click.option("--url", default=None, help="Samyama URL. Omit for the embedded engine.")
@click.option("--graph", "graph_name", default=loader.GRAPH, show_default=True,
              help="Graph, or tenant, to query on the server.")
@click.option("--scale", type=float, default=DEFAULT_SCALE, show_default=True,
              help="Size of the generated layer in embedded mode.")
@click.option("--seed", type=int, default=gen.DEFAULT_SEED, show_default=True)
@click.option("--no-pause", is_flag=True, help="Do not pace the output.")
@click.option("--slides", is_flag=True, help="One query per screen.")
@click.option("--long", "long_form", is_flag=True,
              help="Long form: one tall report, in the case-study layout.")
@click.option("--write-cypher", "only_write", is_flag=True,
              help="Write the ten queries to demo/queries.cypher and exit.")
def main(url, graph_name, scale, seed, no_pause, slides, long_form, only_write):
    if only_write:
        click.echo(f"wrote {write_cypher()}")
        return
    console = Console(width=100)

    if long_form:
        if not url:
            raise click.UsageError("--long needs --url: the recording must not "
                                   "include a minute of loading")
        empty = run_long(console, loader.connect(url), graph_name, not no_pause)
        if empty:
            console.print(f"[red]these steps returned no rows: {', '.join(empty)}[/red]")
            sys.exit(1)
        return

    def pause(seconds: float) -> None:
        if not no_pause:
            time.sleep(seconds)

    console.print(Panel.fit(
        "[bold]Finance Knowledge Graph[/bold]\n"
        "Real companies, banks, legal entities and exchange rates.\n"
        "Generated customers, accounts and payments, kept apart from them.",
        border_style="cyan"))

    try:
        if url:
            client = loader.connect(url)
            console.print(f"[dim]connected to {url}, graph {graph_name}[/dim]\n")
        else:
            graph_name = loader.GRAPH
            console.print(f"[dim]loading into the embedded engine "
                          f"(generated layer at scale {scale}) ...[/dim]")
            began = time.time()
            client, nodes, edges = loader.load_embedded("all", seed, scale)
            console.print(f"[dim]{len(nodes):,} nodes and {len(edges):,} edges loaded "
                          f"and verified in {time.time() - began:.0f}s[/dim]\n")
    except loader.MissingData as exc:
        console.print(f"[red]{exc}[/red]")
        sys.exit(1)

    pause(2.0)
    empty = [query_id for step, (query_id, lead, rows) in enumerate(STORY, start=1)
             if show(console, client, graph_name, step, query_id, lead, rows, pause,
                     slides) == 0]

    if slides:
        console.clear()
    console.print(Panel.fit(
        "[green]Real[/green]   companies, filings, banks, bank failures, legal "
        "entities, exchange rates\n"
        "[yellow]Generated[/yellow]   institutions, customers, accounts, payments, "
        "loans, watchlist, alerts\n\n"
        "Companies and filings: US Securities and Exchange Commission\n"
        "Banks and failures: Federal Deposit Insurance Corporation\n"
        "Legal entities: GLEIF   Exchange rates: European Central Bank\n"
        "Country indicators: World Bank, World Development Indicators (CC BY 4.0)\n"
        "[dim]No generated account, payment or watchlist entry is attached to a real "
        "organisation.[/dim]",
        title="What you just saw", border_style="cyan"))
    pause(5.0)

    if empty:
        console.print(f"[red]these steps returned no rows: {', '.join(empty)}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
