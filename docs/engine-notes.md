# Engine notes

What was observed about the Samyama engine while building this graph.

**Engine used:** the `samyama` Python package, version 1.9.0, embedded, on
macOS x86_64, and a Samyama v1.7.1 server. Observed 2026-09-30.

`samyama` 1.10.0 publishes no wheel for macOS x86_64 and its source build
failed on this machine, so `pyproject.toml` pins `samyama<1.10`.

## Load performance

Measured on the full graph, 69,437 nodes and 149,387 edges: built, loaded and
verified in 301 seconds on the embedded engine. Edges dominate; they are sent
250 to a statement, the batch size measured as fastest for this engine in the
supply chain KG.

## Query performance

Full graph, embedded engine, fastest of five runs:

| Id | ms | |
|---|---:|---|
| FN13 | 131.3 | Cross-border corridors: groups all 36,681 payments |
| FN09 | 75.4 | Three-account rings: a three-edge cycle over the payments |
| FN16 | 73.4 | Provenance split: touches every node |
| FN05 | 62.6 | Ultimate parents of Indian entities: 18,295 ownership edges |
| FN11 | 49.8 | Shared devices |
| FN02 | 25.9 | Holding companies |
| FN04 | 20.6 | Variable-length ownership chain from one entity |
| others | under 11 | |

Every catalog query returns in under 140 ms.

## Habits kept from the supply chain KG

The catalog is written in the defensive style Samyama v1.7.0 required: double
quotes, sorting through a `WITH`, shared variable leading, a tie-breaker under
every `LIMIT`. Every query has a plain-Python reference and the two are
compared on every run. Uniqueness of `id` is a loader invariant; the schema
creates indexes only.

**Not tested:** whether the `graph` parameter isolates tenants on every
version. On the v1.7.1 server used here a probe node written to one tenant
was not visible from another.
