"""Run the query catalog, time it, and check every answer.

    python -m benchmarks.run                         # embedded engine, full graph
    python -m benchmarks.run --scale 0.1             # a smaller generated layer
    python -m benchmarks.run --url http://127.0.0.1:8080
    python -m benchmarks.run --url http://127.0.0.1:8080 --graph finance
    python -m benchmarks.run --query SC06 --show 10  # one query, with its rows

Every answer is checked against the plain-Python reference in
benchmarks/reference.py, and the command exits non-zero if any disagrees. With
--url the graph on the server must have been loaded with the same --seed and
--scale given here, since the reference is rebuilt from them.
"""
from __future__ import annotations

import sys
import time

import click

from benchmarks.queries import QUERIES, render
from benchmarks.reference import Graph, check
from etl import generate as gen
from etl import loader


@click.command()
@click.option("--url", default=None, help="Samyama URL. Omit for the embedded engine.")
@click.option("--graph", "graph_name", default=loader.GRAPH, show_default=True,
              help="Graph, or tenant, to query on the server.")
@click.option("--seed", type=int, default=gen.DEFAULT_SEED, show_default=True)
@click.option("--scale", type=float, default=1.0, show_default=True)
@click.option("--query", "only", multiple=True, help="Run just this query id. Repeatable.")
@click.option("--show", type=int, default=0, help="Print this many rows of each answer.")
@click.option("--repeat", type=int, default=5, show_default=True,
              help="Timed runs per query; the fastest is reported.")
def main(url, graph_name, seed, scale, only, show, repeat):
    unknown = set(only) - {q["id"] for q in QUERIES}
    if unknown:
        raise click.BadParameter(f"no such query: {sorted(unknown)}")

    started = time.time()
    if url:
        nodes, edges, _ = loader.build("all", seed, scale)
        client = loader.connect(url)
        click.echo(f"[graph] {url}, graph {graph_name!r}; reference rebuilt from "
                   f"seed {seed}, scale {scale}")
    else:
        click.echo(f"[graph] loading into the embedded engine (seed {seed}, scale {scale})")
        client, nodes, edges = loader.load_embedded("all", seed, scale)
    click.echo(f"  {len(nodes):,} nodes, {len(edges):,} edges, ready in "
               f"{time.time() - started:.0f}s")
    graph = Graph(nodes, edges)

    failed = 0
    click.echo(f"\n{'id':5} {'layer':10} {'rows':>5} {'ms':>8}  result")
    for entry in QUERIES:
        if only and entry["id"] not in only:
            continue
        statement = render(entry)
        best, rows = None, []
        for _ in range(max(1, repeat)):
            began = time.perf_counter()
            result = client.query(statement, graph_name if url else loader.GRAPH)
            took = 1000 * (time.perf_counter() - began)
            best = took if best is None else min(best, took)
            rows = result.records
        problems = check(entry, rows, graph)
        failed += bool(problems)
        click.echo(f"{entry['id']:5} {entry['layer']:10} {len(rows):>5} {best:>8.1f}  "
                   f"{'ok' if not problems else 'WRONG'}  {entry['title']}")
        for problem in problems[:5]:
            click.echo(f"        ! {problem}", err=True)
        if show:
            click.echo(f"        {result.columns}")
            for row in rows[:show]:
                click.echo(f"        {row}")

    if failed:
        click.echo(f"\n{failed} quer{'y' if failed == 1 else 'ies'} disagreed with "
                   f"the reference", err=True)
        sys.exit(1)
    click.echo("\nevery answer agrees with the reference")


if __name__ == "__main__":
    main()
