# Benchmarks

Sixteen questions, each answered twice.

| File | |
|---|---|
| `queries.py` | The catalog: the question, why it suits a graph, the Cypher, its parameters |
| `reference.py` | Each query again in plain Python, and `check()`, which compares the two |
| `run.py` | Runs, times and checks the catalog |

```bash
python -m benchmarks.run                     # full graph, embedded engine
python -m benchmarks.run --scale 0.1         # smaller generated layer
python -m benchmarks.run --query FN09 --show 10
python -m benchmarks.run --url http://127.0.0.1:8080 --graph finance
```

The command exits non-zero if any answer disagrees with its reference.

## Why every query has a reference

A query that runs has not been shown to be right. `check()` tests four things,
because each can fail on its own:

1. the number of rows;
2. that every row is one the reference also produced;
3. that the rows are in the promised order;
4. under a `LIMIT`, that they are the top rows and not just any correct ones.

## Adding a query

1. Add an entry to `QUERIES` in `queries.py`, with `layer` and default `params`.
2. Add its reference to `reference.py`, written from the question, not from the
   Cypher.
3. If the defaults name something the test fixture lacks, add an override to
   `FIXTURE_PARAMS` in `tests/test_query_answers.py`.
4. Run `pytest`. A query with no reference, or one that returns nothing on the
   fixture or on the full graph, fails.

## Results

Full graph, 69,437 nodes and 149,387 edges, embedded engine, macOS x86_64,
`samyama` 1.9.0. Fastest of five runs, measured 2026-09-30. Every answer agreed
with its reference.

| Id | Layer | Rows | ms |
|---|---|---:|---:|
| FN01 | real | 17 | 3.9 |
| FN02 | real | 10 | 25.9 |
| FN03 | real | 10 | 7.9 |
| FN04 | real | 3 | 20.6 |
| FN05 | real | 10 | 62.6 |
| FN06 | real | 10 | 4.3 |
| FN07 | real | 10 | 1.2 |
| FN08 | real | 6 | 0.2 |
| FN09 | synthetic | 6 | 75.4 |
| FN10 | synthetic | 10 | 3.9 |
| FN11 | synthetic | 10 | 49.8 |
| FN12 | synthetic | 10 | 3.3 |
| FN13 | both | 10 | 131.3 |
| FN14 | both | 10 | 8.3 |
| FN15 | synthetic | 10 | 10.0 |
| FN16 | both | 2 | 73.4 |

One machine, one run of the suite. Treat these as an order of magnitude, not a
benchmark result.
