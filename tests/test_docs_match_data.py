"""The schema is written down in several places; this pins them together.

The schema file declares the labels twice -- in its header and as one
`CREATE INDEX` per label -- the loader declares them again, the README and the
data card list them, and the generator is what actually produces them. Nothing
connected these, which is how a label comes to be loaded but missing from the
document that describes it.

The first half parses prose and code and needs no data. The second half checks
the COUNTS quoted in the documents against a real build, and skips when
data/raw/ has not been downloaded.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pytest

from benchmarks.queries import QUERIES
from etl import download_data, loader

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "schema" / "finance_kg.cypher"
README = ROOT / "README.md"
CARD = ROOT / "DATASET_CARD.md"
SCHEMA_DOC = ROOT / "docs" / "schema.md"
PROVENANCE = ROOT / "docs" / "data-provenance.md"


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def declared_in_header(heading: str) -> list[str]:
    match = re.search(rf"^// {heading} \(\d+\):(.*?)^//\s*$", text(SCHEMA),
                      re.DOTALL | re.MULTILINE)
    assert match, f"no `// {heading} (n):` block in {SCHEMA.name}"
    body = re.sub(r"^//", "", match.group(1), flags=re.MULTILINE)
    return [name.strip() for name in body.split(",") if name.strip()]


def declared_count(heading: str) -> int:
    match = re.search(rf"^// {heading} \((\d+)\):", text(SCHEMA), re.MULTILINE)
    assert match, f"no count in the `// {heading} (n):` header"
    return int(match.group(1))


def shapes() -> list[tuple[str, str, str]]:
    return re.findall(r"^// \(:(\w+)\)-\[:(\w+)[^\]]*\]->\(:(\w+)\)", text(SCHEMA),
                      re.MULTILINE)


def listed(doc: Path, heading: str, separator: str) -> list[str]:
    match = re.search(rf"\*\*\d+ {heading}\*\* {separator} (.*?)\n\n", text(doc), re.DOTALL)
    assert match, f"no `**n {heading}**` list in {doc.name}"
    return [name.strip() for name in match.group(1).replace("\n", " ").split(",")]


def number(value: str) -> int:
    return int(value.replace(",", ""))


# --------------------------------------------------------------------------
# the schema file must agree with itself, the loader and the documents
# --------------------------------------------------------------------------

def test_header_counts_match_the_lists():
    for heading in ("Node labels", "Edge types"):
        names = declared_in_header(heading)
        assert len(names) == declared_count(heading), (heading, len(names))
        assert len(set(names)) == len(names), f"duplicate in {heading}"


def test_every_declared_label_has_an_id_index():
    indexed = re.findall(r"^CREATE INDEX ON :(\w+)\(id\);", text(SCHEMA), re.MULTILINE)
    assert sorted(indexed) == sorted(declared_in_header("Node labels"))


def test_loader_labels_match_the_schema_header():
    assert loader.NODE_LABELS == declared_in_header("Node labels")


def test_every_declared_edge_has_a_documented_shape():
    assert {edge for _, edge, _ in shapes()} == set(declared_in_header("Edge types"))


def test_every_shape_joins_declared_labels():
    labels = set(declared_in_header("Node labels"))
    for src, edge, dst in shapes():
        assert src in labels and dst in labels, (src, edge, dst)


def test_the_readme_and_card_list_the_same_schema():
    for doc, sep in ((README, "—"), (CARD, "--")):
        assert listed(doc, "node labels", sep) == declared_in_header("Node labels")
        assert listed(doc, "edge types", sep) == declared_in_header("Edge types")


def test_the_build_produces_exactly_the_declared_schema(full_graph):
    nodes, edges, _ = full_graph
    assert {n["_label"] for n in nodes} == set(declared_in_header("Node labels"))
    assert {e["_type"] for e in edges} == set(declared_in_header("Edge types"))


def test_every_edge_built_has_a_documented_shape(full_graph):
    nodes, edges, _ = full_graph
    label = {n["id"]: n["_label"] for n in nodes}
    built = {(label[e["src"]], e["_type"], label[e["dst"]]) for e in edges}
    assert built <= set(shapes()), sorted(built - set(shapes()))


def test_the_real_shapes_in_the_schema_are_the_ones_the_loader_allows():
    real = text(SCHEMA).split("// --- Real edges")[1].split("// --- Generated")[0]
    documented = set(re.findall(r"^// \(:(\w+)\)-\[:(\w+)", real, re.MULTILINE))
    assert {(edge, label) for label, edge in documented} == loader.REAL_EDGES


def test_only_real_shaped_edges_are_stamped_real(full_graph):
    nodes, edges, _ = full_graph
    label = {n["id"]: n["_label"] for n in nodes}
    for e in edges:
        shaped = (e["_type"], label[e["src"]]) in loader.REAL_EDGES
        assert (e["provenance"] == "real") == shaped, (e["_type"], e["src"])


# --------------------------------------------------------------------------
# sources
# --------------------------------------------------------------------------

def test_every_source_is_in_the_provenance_document():
    section = text(PROVENANCE).split("\n## Sources\n")[1].split("\n## ")[0]
    documented = re.findall(r"^\| `(\w+)` \|", section, re.MULTILINE)
    assert sorted(documented) == sorted(download_data.SOURCES)


def test_every_source_states_its_terms():
    for key, src in download_data.SOURCES.items():
        for field in ("title", "publisher", "url", "page", "licence", "citation", "file"):
            assert src.get(field), f"{key} has no {field}"
        assert src["kind"] in download_data.FETCHERS, key


def test_every_source_allows_any_use():
    """This graph is built to be shown in public. A source with a restriction
    on use may not be added."""
    for key, src in download_data.SOURCES.items():
        assert src["licence"] in download_data.ALLOWED_LICENCES, (key, src["licence"])


def test_no_restricted_source_is_reached():
    """Services whose terms restrict reuse, or that need a key, are not fetched
    from. Naming one in a comment is fine; fetching from it is not."""
    banned = ("portwatch", "imf.org", "nseindia", "bseindia", "rbi.org.in",
              "iso20022.org", "opensanctions", "treasury.gov")
    for folder in ("etl", "benchmarks", "mcp_server", "demo"):
        for path in sorted((ROOT / folder).glob("*.py")):
            lowered = text(path).lower()
            for word in banned:
                assert word not in lowered, f"{word} appears in {folder}/{path.name}"


def test_no_contact_address_is_written_into_the_code():
    for path in sorted((ROOT / "etl").glob("*.py")):
        assert not re.search(r"[\w.]+@[\w.]+\.\w+", text(path)), path.name


def test_the_credits_owed_are_stated():
    for doc in (README, CARD, PROVENANCE):
        assert "World Bank" in text(doc) and "European Central Bank" in text(doc), doc.name


def test_no_downloaded_data_is_tracked():
    assert re.search(r"^/data/$", text(ROOT / ".gitignore"), re.MULTILINE)


# --------------------------------------------------------------------------
# the query catalog
# --------------------------------------------------------------------------

def test_the_readme_lists_every_query_with_its_layer():
    found = dict(re.findall(r"^\| (FN\d\d) \| (\w+) \|", text(README), re.MULTILINE))
    shown = {"real": "real", "both": "both", "synthetic": "generated"}
    assert found == {q["id"]: shown[q["layer"]] for q in QUERIES}


def test_catalog_entries_are_well_formed():
    ids = [q["id"] for q in QUERIES]
    assert len(set(ids)) == len(ids)
    for q in QUERIES:
        for field in ("title", "question", "why_graph", "cypher"):
            assert q[field].strip(), (q["id"], field)
        assert q["layer"] in ("real", "synthetic", "both"), q["id"]
        used = set(re.findall(r"\$([a-z_][a-z0-9_]*)", q["cypher"]))
        assert used == set(q["params"]), (q["id"], used, set(q["params"]))


def test_queries_only_use_declared_labels_and_edges():
    labels = set(declared_in_header("Node labels"))
    edges = set(declared_in_header("Edge types"))
    for q in QUERIES:
        for label in re.findall(r"\(\w*:(\w+)", q["cypher"]):
            assert label in labels, (q["id"], label)
        for edge in re.findall(r"\[\w*:(\w+)", q["cypher"]):
            assert edge in edges, (q["id"], edge)


def test_a_query_marked_real_touches_no_generated_label():
    for q in QUERIES:
        if q["layer"] == "real":
            used = set(re.findall(r"\(\w*:(\w+)", q["cypher"]))
            assert used <= set(loader.REAL_LABELS), (q["id"], used)


def test_no_query_joins_generated_activity_to_a_real_organisation():
    """A query cannot walk an edge the graph does not have, but it could name
    a real bank in a WHERE beside generated accounts. It must not."""
    organisations = set(loader.REAL_LABELS) - loader.NEUTRAL_LABELS - {"ExchangeRate"}
    for q in QUERIES:
        used = set(re.findall(r"\(\w*:(\w+)", q["cypher"]))
        if used & set(loader.SYNTHETIC_LABELS):
            assert not used & organisations, (q["id"], used & organisations)


def test_a_limited_query_breaks_its_ties():
    for q in QUERIES:
        if "LIMIT" not in q["cypher"]:
            continue
        order = re.search(r"ORDER BY (.+?)\nLIMIT", q["cypher"], re.DOTALL).group(1)
        assert len(order.split(",")) >= 2, (q["id"], "one sort key and a LIMIT")


def test_the_readme_counts_the_mcp_tools():
    import asyncio

    from mcp_server.server import mcp
    tools = asyncio.run(mcp.list_tools())
    assert f"# {len(tools)} tools" in text(README)


# --------------------------------------------------------------------------
# the counts quoted in the documents, against a real build
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def real_build():
    if download_data.missing():
        pytest.skip("data/raw/ is not downloaded; run `python -m etl.download_data`")
    nodes, edges, dropped = loader.build("all")
    assert loader.check_integrity(nodes, edges) == []
    return nodes, edges, dropped


def test_headline_counts(real_build):
    nodes, edges, _ = real_build
    real = sum(1 for n in nodes if n["provenance"] == "real")
    real_edges = sum(1 for e in edges if e["provenance"] == "real")
    for doc in (README, CARD):
        assert f"**{len(nodes):,} nodes. {len(edges):,} edges." in text(doc), doc.name
    assert f"| **Real** | {real:,} | {real_edges:,} |" in text(README)
    assert (f"| **Generated** | {len(nodes) - real:,} | "
            f"{len(edges) - real_edges:,} |") in text(README)
    assert f"{len(download_data.SOURCES)} public sources" in text(README)
    for doc in (CARD, PROVENANCE):
        assert f"| Real | {real:,} | {real_edges:,} |" in text(doc), doc.name
        assert (f"| Generated | {len(nodes) - real:,} | "
                f"{len(edges) - real_edges:,} |") in text(doc), doc.name
    assert f"**{100 * real / len(nodes):.1f}% of nodes are real.**" in text(CARD)
    assert f"{len(nodes):,} nodes and {len(edges):,} edges" in text(
        ROOT / "benchmarks" / "README.md")


def test_label_counts_in_the_documents(real_build):
    nodes, _, _ = real_build
    built = Counter(n["_label"] for n in nodes)
    quoted = {label: number(count) for label, count in
              re.findall(r"^\| (\w+) \| ([\d,]+) \| `", text(SCHEMA_DOC), re.MULTILINE)}
    assert quoted == dict(built)
    card = {label: (number(count), layer) for label, count, layer in
            re.findall(r"^\| (\w+) \| ([\d,]+) \| (real|generated) \|$", text(CARD),
                       re.MULTILINE)}
    assert {k: v[0] for k, v in card.items()} == dict(built)
    for label, (_, layer) in card.items():
        assert (layer == "real") == (label in loader.REAL_LABELS), label
    generated = text(PROVENANCE).split("## The generated layer")[1]
    quoted = {label: number(count) for label, count in
              re.findall(r"^\| (\w+) \| ([\d,]+) \|", generated, re.MULTILINE)}
    assert quoted == {label: built[label] for label in loader.SYNTHETIC_LABELS}


def test_edge_counts_in_the_schema_document(real_build):
    _, edges, _ = real_build
    built = Counter(e["_type"] for e in edges)
    quoted: Counter = Counter()
    for edge, count in re.findall(r"^\| ([A-Z_]+) \| .*? \| ([\d,]+) \|$",
                                  text(SCHEMA_DOC), re.MULTILINE):
        quoted[edge] += number(count)       # shared edge types are listed per layer
    assert dict(quoted) == dict(built)


def test_dropped_rows_in_the_provenance_document(real_build):
    _, _, dropped = real_build
    doc = text(PROVENANCE)
    for reason, count in dropped.items():
        assert f"| `{reason}` | {count:,} |" in doc, reason
    assert len(re.findall(r"^\| `\w+` \| [\d,]+ \|", doc.split("## What is left out")[1]
                          .split("\n## ")[0], re.MULTILINE)) == len(dropped)


def test_pattern_counts_in_the_provenance_document(real_build):
    _, edges, _ = real_build
    patterns = Counter(e["pattern"] for e in edges if e["_type"] == "TRANSFER")
    doc = text(PROVENANCE)
    for pattern, count in patterns.items():
        assert f"| `{pattern}` | {count:,} |" in doc, pattern
    assert f"{sum(patterns.values()):,} `TRANSFER` edges" in doc


def test_every_query_has_an_answer_on_the_full_graph(real_build):
    from benchmarks.reference import REFERENCES, Graph
    nodes, edges, _ = real_build
    graph = Graph(nodes, edges)
    for q in QUERIES:
        rows, _ = REFERENCES[q["id"]](graph, **q["params"])
        assert rows, f"{q['id']} has no answer on the full graph with its defaults"


def test_no_generated_name_is_the_name_of_something_real_in_the_full_graph(real_build):
    nodes, _, _ = real_build
    real = {n["name"].lower() for n in nodes
            if n["provenance"] == "real" and isinstance(n.get("name"), str)}
    clashes = [n["name"] for n in nodes
               if n["provenance"] == "synthetic" and isinstance(n.get("name"), str)
               and n["name"].lower() in real]
    assert clashes == []


def test_the_demo_runs_ten_distinct_catalog_queries():
    from demo.demo import STORY
    ids = [query_id for query_id, _lead, _rows in STORY]
    assert len(ids) == 10 and len(set(ids)) == 10
    assert set(ids) <= {q["id"] for q in QUERIES}


def test_every_demo_query_has_an_answer_at_demo_scale(real_build):
    from benchmarks.reference import REFERENCES, Graph
    from demo.demo import DEFAULT_SCALE, STORY
    nodes, edges, _ = loader.build("all", scale=DEFAULT_SCALE)
    graph = Graph(nodes, edges)
    by_id = {q["id"]: q for q in QUERIES}
    for query_id, _lead, _rows in STORY:
        rows, _ = REFERENCES[query_id](graph, **by_id[query_id]["params"])
        assert rows, f"{query_id} has no answer at demo scale {DEFAULT_SCALE}"


# --------------------------------------------------------------------------
# the demo recording
# --------------------------------------------------------------------------

def test_the_demo_readme_lists_the_story_in_order():
    from demo.demo import STORY
    shown = {"real": "real", "both": "both", "synthetic": "generated"}
    by_id = {q["id"]: q for q in QUERIES}
    found = re.findall(r"^\| (\d+) \| (FN\d\d) \| (\w+) \|", text(ROOT / "demo" / "README.md"),
                       re.MULTILINE)
    assert found == [(str(step), query_id, shown[by_id[query_id]["layer"]])
                     for step, (query_id, _lead, _rows) in enumerate(STORY, start=1)]


def test_the_written_queries_are_the_ones_the_demo_runs(tmp_path):
    from demo.demo import CYPHER_PATH, write_cypher
    fresh = write_cypher(tmp_path / "queries.cypher").read_text(encoding="utf-8")
    assert CYPHER_PATH.read_text(encoding="utf-8") == fresh


def test_the_recording_is_in_place_and_shown():
    demo = ROOT / "demo"
    header = (demo / "finance-kg.gif").read_bytes()[:10]
    assert header[:6] in (b"GIF87a", b"GIF89a")
    width = int.from_bytes(header[6:8], "little")
    height = int.from_bytes(header[8:10], "little")
    assert f"{width} by {height} pixels" in text(demo / "README.md")
    assert height > 3 * width, "the recording is long form: one tall report"
    assert "demo/finance-kg.gif" in text(README)


def test_the_recording_shows_every_query_and_the_credits():
    import json

    from demo.demo import SOURCES_LINE, STORY
    lines = (ROOT / "demo" / "finance-kg.cast").read_text(encoding="utf-8").splitlines()
    shown = "".join(json.loads(line)[2] for line in lines[1:] if line.startswith("["))
    shown = re.sub(r"\x1b\[[0-9;]*m", "", shown)
    by_id = {q["id"]: q for q in QUERIES}
    for query_id, _lead, _rows in STORY:
        assert by_id[query_id]["title"] in shown, query_id
    for credit in ("World Bank (CC BY 4.0)", "ECB", "SEC", "FDIC", "GLEIF"):
        assert credit in SOURCES_LINE and credit in shown, credit
    assert "No real person or company is among them" in shown
    counts = [int(n) for n in re.findall(r"→ (\d+) row\(s\) in", shown)]
    assert len(counts) == len(STORY) and all(counts), counts


def test_the_recording_holds_its_last_frame():
    script = text(ROOT / "demo" / "record.sh")
    assert 'HOLD="${GIF_HOLD:-14}"' in script and '--last-frame-duration "$HOLD"' in script
    assert "held for 14 seconds" in text(ROOT / "demo" / "README.md")
