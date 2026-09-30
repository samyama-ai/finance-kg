"""Shared ETL helpers, and the one door every node and edge goes through.

`node()` and `edge()` are that door. Nothing else in this repo constructs a
node or an edge directly. Provenance is stamped here, at the moment of
construction, so there is no code path that can produce one without it -- which
matters in this graph more than most, because the real layer (companies, banks,
legal entities, exchange rates) and the generated layer (customers, accounts,
transfers, loans) sit in one graph and are queried together.

Shapes follow interconnect-ip-kg/etl/helpers.py so the two repos behave the same
way against the same engine.
"""
from __future__ import annotations

import random
import re

REAL = "real"
SYNTHETIC = "synthetic"
GENERATED_SOURCE = "generated"


def norm_id(prefix: str, value: str) -> str:
    """From the repo template. Kept because tests/test_smoke.py pins it."""
    return f"{prefix}:{value.strip().lower().replace(' ', '_')}"


def slug(value: str) -> str:
    """`Plastics, Rubber, Leather` -> `plastics_rubber_leather`."""
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def rid(prefix: str, n: int, width: int = 6) -> str:
    """A deterministic id: `shipment:000007`. Stable across runs for a seed."""
    return f"{prefix}:{n:0{width}d}"


def node(label: str, node_id: str, provenance: str, source: str, **props) -> dict:
    """Build one node. The only sanctioned way to make one.

    Raises on a missing or unknown provenance rather than defaulting: a
    generated shipment inheriting "real" because somebody forgot an argument is
    exactly the failure the stamping exists to prevent.
    """
    if provenance not in (REAL, SYNTHETIC):
        raise ValueError(
            f"{node_id}: provenance must be {REAL!r} or {SYNTHETIC!r}, got {provenance!r}"
        )
    if not source:
        raise ValueError(f"{node_id}: every node needs a source, or {GENERATED_SOURCE!r}")
    if provenance == REAL and source == GENERATED_SOURCE:
        raise ValueError(f"{node_id}: a real node cannot have source={GENERATED_SOURCE!r}")
    if provenance == SYNTHETIC and source != GENERATED_SOURCE:
        raise ValueError(
            f"{node_id}: a synthetic node must have source={GENERATED_SOURCE!r}, "
            f"got {source!r} -- a generated node carrying a real URL is how "
            f"invented figures come to look sourced"
        )
    out = {"id": node_id, "_label": label, "provenance": provenance, "source": source}
    out.update(props)
    return out


def edge(edge_type: str, src: str, dst: str, provenance: str, **props) -> dict:
    """Build one edge. Endpoints are ids; the loader resolves them.

    Edges are stamped too, and have to be. A generated customer is BASED_IN a
    REAL country, so the provenance of an edge cannot be read off one end of
    it: it needs a stamp of its own.
    """
    if not src or not dst:
        raise ValueError(f"{edge_type}: both endpoints required, got {src!r} -> {dst!r}")
    if provenance not in (REAL, SYNTHETIC):
        raise ValueError(
            f"{edge_type} {src} -> {dst}: provenance must be {REAL!r} or "
            f"{SYNTHETIC!r}, got {provenance!r}"
        )
    return {"_type": edge_type, "src": src, "dst": dst, "provenance": provenance, **props}


def seeded(seed: int) -> random.Random:
    """An isolated RNG, deliberately NOT the module-level `random`.

    A shared global means one extra draw anywhere shifts every later value, and
    the generated layer stops being reproducible for reasons nobody can find.
    """
    return random.Random(seed)


def weighted_pick(rng: random.Random, items: list, weights: list[float]):
    """One item, chosen by weight. `rng.choices` returns a list; this does not."""
    return rng.choices(items, weights=weights, k=1)[0]


def to_float(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def to_int(value) -> int | None:
    number = to_float(value)
    return None if number is None else int(round(number))


# --------------------------------------------------------------------------
# Cypher emission
# --------------------------------------------------------------------------

def chunked(rows, size: int):
    for i in range(0, len(rows), size):
        yield rows[i:i + size]


def cypher_literal(value) -> str:
    """A Cypher literal.

    Strings are DOUBLE-quoted and escaped. Company names carry apostrophes and
    quotes ("Macy's", "O'Reilly"), and one unescaped quote is a syntax error
    hundreds of statements into a load.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    text = text.replace("\n", " ").replace("\r", " ")
    return f'"{text}"'


def props_map(row: dict) -> str:
    """`{a: 1, b: "x"}` from a node or edge dict.

    Keys starting with `_` are loader metadata and never reach the graph. Null
    values are dropped rather than written: a company that reported no revenue
    figure has no `revenue_usd` property at all, so it cannot be mistaken for
    a company that earned nothing.
    """
    parts = [
        f"{k}: {cypher_literal(v)}"
        for k, v in row.items()
        if not k.startswith("_") and v is not None
    ]
    return "{" + ", ".join(parts) + "}"


def edge_props(e: dict) -> dict:
    return {k: v for k, v in e.items()
            if not k.startswith("_") and k not in ("src", "dst")}


def create_nodes(client, graph: str, label: str, rows, batch: int = 250) -> int:
    """Batch-CREATE nodes of one label. Returns how many were sent."""
    total = 0
    for group in chunked(list(rows), batch):
        parts = [f"(:{label} {props_map(r)})" for r in group]
        client.query("CREATE " + ", ".join(parts), graph)
        total += len(group)
    return total


def create_edges(client, graph: str, edges, label_of: dict, batch: int = 250) -> int:
    """Batch-CREATE edges, resolving endpoints by their unique `id`.

    `label_of` maps node id -> label, so each endpoint MATCH is anchored on a
    label and hits the id index rather than scanning every node.

    The batch size is measured, not guessed: on the full graph 250 edges per
    statement loads at about 1.1 ms an edge, against 1.6 ms at 100, 5 ms at 25
    and 2 ms at 1,000. Small batches pay the per-statement cost too often and
    large ones pay for the size of the MATCH.
    """
    total = 0
    for group in chunked(list(edges), batch):
        var_of: dict[str, str] = {}
        match_parts, where_parts, create_parts = [], [], []
        for e in group:
            for node_id in (e["src"], e["dst"]):
                if node_id not in var_of:
                    var = f"v{len(var_of)}"
                    var_of[node_id] = var
                    match_parts.append(f"({var}:{label_of[node_id]})")
                    where_parts.append(f"{var}.id = {cypher_literal(node_id)}")
            props = edge_props(e)
            rel = f"[:{e['_type']}" + (f" {props_map(props)}]" if props else "]")
            create_parts.append(f"({var_of[e['src']]})-{rel}->({var_of[e['dst']]})")
        client.query(
            "MATCH " + ", ".join(match_parts)
            + " WHERE " + " AND ".join(where_parts)
            + " CREATE " + ", ".join(create_parts),
            graph,
        )
        total += len(group)
    return total
