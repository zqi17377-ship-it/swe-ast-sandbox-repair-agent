# SWE Code Repair Agent — 12-Repository Benchmark & 3-Way Ablation Report

## 1. Executive Ablation Summary

| Ablation Configuration | Resolved Pass@1 | First-Turn Pass | Self-Healed (T2–4) | Avg Context Tokens | Token Reduction (vs Raw / vs Base) | Avg Turns | Avg Sandbox Time |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Baseline 1: Single-Shot Full-Context (max_turns=1)** | **3/12 (25.0%)** | 3/12 (25.0%) | 0/12 (0.0%) | 1480.0 | 21.1% / 0.0% | 1.00 | 1.24s |
| **Baseline 2: Multi-Turn Full-Context (max_turns=4)** | **6/12 (50.0%)** | 3/12 (25.0%) | 3/12 (25.0%) | 1470.8 | 21.2% / -0.7% | 2.75 | 3.87s |
| **Ours: AST Localization + Sandbox Self-Healing (max_turns=4)** | **10/12 (83.3%)** | 4/12 (33.3%) | 6/12 (50.0%) | 856.8 | 54.2% / 41.4% | 2.17 | 5.39s |

## 2. Per-Repository Outcome Matrix

| Task ID | Category | B1: Single-Shot Full | B2: Multi-Turn Full | Ours: AST + Self-Healing | Ours Context Tokens (Raw) |
| :--- | :--- | :---: | :---: | :---: | :---: |
| `01_lru_ttl_cache` | State & Cache Eviction | FAIL (LOCALIZATION_TRUNCATION_MISS) | FAIL (LOCALIZATION_TRUNCATION_MISS) | **PASS: HEALED (T2)** | 1132 (2812) |
| `02_dag_scheduler` | Graph Algorithms | PASS: PASS (T1) | PASS: PASS (T1) | **PASS: PASS (T1)** | 878 (2104) |
| `03_token_bucket_limiter` | Rate Limiting & Floating-Point State | FAIL (SINGLE_SHOT_EDGE_CASE_MISS) | PASS: HEALED (T2) | **PASS: HEALED (T2)** | 746 (1747) |
| `04_sql_query_builder` | Query Compilation | FAIL (SINGLE_SHOT_EDGE_CASE_MISS) | PASS: HEALED (T2) | **PASS: HEALED (T3)** | 717 (2068) |
| `05_config_deep_merge` | Immutability & Data Structures | PASS: PASS (T1) | PASS: PASS (T1) | **PASS: PASS (T1)** | 675 (1624) |
| `06_pagination_cursor` | API Pagination | FAIL (LOCALIZATION_TRUNCATION_MISS) | FAIL (LOCALIZATION_TRUNCATION_MISS) | **PASS: PASS (T1)** | 993 (1880) |
| `07_event_bus_pubsub` | Concurrency & Pub/Sub Routing | PASS: PASS (T1) | PASS: PASS (T1) | **PASS: PASS (T1)** | 697 (1290) |
| `08_retry_circuit_breaker` | Distributed Resilience State Machine | FAIL (LOCALIZATION_TRUNCATION_MISS) | FAIL (LOCALIZATION_TRUNCATION_MISS) | **PASS: HEALED (T2)** | 875 (2282) |
| `09_interval_merger` | Computational Geometry / Timelines | FAIL (LOCALIZATION_TRUNCATION_MISS) | FAIL (LOCALIZATION_TRUNCATION_MISS) | **PASS: HEALED (T3)** | 815 (1520) |
| `10_ledger_reconciler` | Financial Accounting Invariants | FAIL (LOCALIZATION_TRUNCATION_MISS) | FAIL (LOCALIZATION_TRUNCATION_MISS) | **FAIL (CROSS_MODULE_INVARIANT_OSCILLATION)** | 993 (1670) |
| `11_dependency_injector` | Reflection & Object Lifetimes | FAIL (LOCALIZATION_TRUNCATION_MISS) | FAIL (LOCALIZATION_TRUNCATION_MISS) | **FAIL (DYNAMIC_DISPATCH_GRAPH_MISS)** | 748 (1823) |
| `12_markdown_table_parser` | Stateful Lexical Analysis | FAIL (SINGLE_SHOT_EDGE_CASE_MISS) | PASS: HEALED (T2) | **PASS: HEALED (T2)** | 1014 (1623) |

## 3. Failure Case Attribution Analysis (`Ours` & Baselines)

### 3.1 Unresolved Tasks in `Ours: AST Localization + Sandbox Self-Healing`

| Task ID | Turns Used | Final Pytest Status | Failure Category | Root-Cause Attribution |
| :--- | :---: | :---: | :--- | :--- |
| `10_ledger_reconciler` | 4 | 2P / 1F | `CROSS_MODULE_INVARIANT_OSCILLATION` | Patches across ledger_reconciler/allocator.py, ledger_reconciler/reconciler.py fixed local assertions while violating coupled cross-module conservation invariants. |
| `11_dependency_injector` | 4 | 2P / 1F | `DYNAMIC_DISPATCH_GRAPH_MISS` | Target symbol invoked via dynamic `getattr` reflection was absent from static AST Top-K. |

### 3.2 Aggregate Failure Distribution Across Ablations

| Failure Category | B1: Single-Shot Full | B2: Multi-Turn Full | Ours: AST + Self-Healing |
| :--- | :---: | :---: | :---: |
| `CROSS_MODULE_INVARIANT_OSCILLATION` | 0 | 0 | 1 |
| `DYNAMIC_DISPATCH_GRAPH_MISS` | 0 | 0 | 1 |
| `LOCALIZATION_TRUNCATION_MISS` | 6 | 6 | 0 |
| `SINGLE_SHOT_EDGE_CASE_MISS` | 3 | 0 | 0 |
