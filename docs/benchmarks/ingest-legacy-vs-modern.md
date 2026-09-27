# Ingest: C++11 legacy vs C++20 modern (final, increment 6)

The C++11 legacy ingester is retired in increment 6. From then on, the AI reads
the C++20 ingester's tables (`ai.v_raw_news` → `ingest.vendor_news_raw`). This
is the last comparison of the two, measured on the same machine on 2026-09-26.

## Correctness: parity

| Check | Result |
|---|---|
| Parity runs (`ingest.parity_run`, 2026-09-19 … 2026-09-24) | 21 runs, **21 PASS, 0 differences** |
| Legacy rows that the C++20 tables don't have | **0** |

With zero differences, switching the views changes nothing the AI sees. The AI
results stay attached to the same items, because `ai.news_item` is keyed by
(feed date, vendor item id) and not by the raw row id.

## Micro-benchmarks (Google Benchmark, release builds)

Command: `make -C python bench`. Each benchmark ran 5 times; the tables show the
median. Host: 6 WSL CPUs at 2.4 GHz (i5-9300H). The rest of the stack was
running (load average 4–5), so the absolute numbers are pessimistic for both.
The ratios are what matter.

| Benchmark | C++11 legacy | C++20 modern | Speed-up |
|---|---:|---:|---:|
| Parse one item (RapidJSON DOM vs simdjson on-demand) | 1,589 ns | 366 ns | 4.3× |
| Content hash of one item (normalize + SHA-256) | 1,980 ns | 1,431 ns | 1.4× |
| Queue ping-pong, one item (mutex + condvar vs Vyukov MPMC ring) | 23.4 ns | 12.4 ns | 1.9× |
| Queue producer/consumer throughput | 0.95 M items/s | 27.5 M items/s | 29× |
| Process a 100-item feed, 1 worker | 1.116 ms | 0.232 ms | 4.8× |
| Process a 100-item feed, 2 workers | 0.862 ms | 0.185 ms | 4.7× |
| Process a 100-item feed, 4 workers | 2.945 ms | 0.219 ms | 13.4× |
| Process a 100-item feed, 8 workers | 3.335 ms | 0.216 ms | 15.4× |

Legacy gets slower with more workers. It creates its thread pool on every call,
which is how the legacy job runs, and its single mutex queue is contended. The
C++20 pool is created once and sleeps on `atomic::wait` between feeds, so extra
workers cost almost nothing. With about 100 items there's too little work to
split, so 2 workers is the sweet spot for both.

## Production runs (`legacy.ingest_run` vs `ingest.ingest_run`)

These are the medians over every DONE run of the demo days, 2026-09-19 …
2026-09-24: 40 legacy runs and 21 C++20 runs. The latency is measured per item,
from parse to hash.

| Metric | C++11 legacy | C++20 modern |
|---|---:|---:|
| Per-item p50 | 7.5 µs | 2 µs |
| Per-item p99 | 108.5 µs | 54 µs |
| Per-item p99.9 | 136.5 µs | 83 µs |
| Whole run (fetch + parse + COPY) | 150.5 ms | 172 ms |

In both ingesters the whole run is dominated by the HTTP fetch of the feed
(C++20 median: fetch 164 ms, parse 103 µs, dedup 111 µs, COPY 5 ms). A faster
parser doesn't shorten it. The C++20 gains are in the per-item tail
(p99 and p99.9 about halved) and in how it scales with workers. Those gains
matter once a feed has thousands of items instead of 100.

## What changed in increment 6

- `ai.v_raw_news` / `ai.v_ingest_run` read `ingest.*` (Alembic migration 0006).
- The C++20 ingester runs in the default `ai` profile at 05:30 ET. The legacy
  container is under the opt-in profile `legacy` (for before/after videos).
- `LEGACY_INGEST=true` brings back the parallel legacy run and the parity check
  in `make -C python demo`.
