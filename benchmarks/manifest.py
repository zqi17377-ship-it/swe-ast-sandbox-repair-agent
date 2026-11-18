"""Registry and metadata loader for the 12 multi-file Python repair tasks."""

from __future__ import annotations

from pathlib import Path

from swe_repair_agent.models import TaskSpec

BENCHMARKS_ROOT = Path(__file__).resolve().parent

BENCHMARK_TASKS: list[TaskSpec] = [
    TaskSpec(
        task_id="01_lru_ttl_cache",
        title="LRUTTLCache stale key retention & TTL expiry boundary",
        repo_rel_path="benchmarks/tasks/01_lru_ttl_cache",
        difficulty="medium",
        category="State & Cache Eviction",
        issue_description=(
            "Expired entries in `LRUTTLCache.get()` return `default` (`None`), "
            "but the expired key remains stored in `self._entries` (`len(cache)` stays non-zero). "
            "Furthermore, when `LRUTTLCache.put()` inserts a new key at `max_size` capacity, "
            "it immediately pops the oldest entry without first purging expired entries, "
            "evicting live keys prematurely."
        ),
        ground_truth_symbols=[
            "lru_ttl_cache/store.py::LRUTTLCache.get",
            "lru_ttl_cache/store.py::LRUTTLCache.put",
            "lru_ttl_cache/expiry.py::is_expired",
        ],
    ),
    TaskSpec(
        task_id="02_dag_scheduler",
        title="DAGScheduler deterministic tie-breaking & cycle detection",
        repo_rel_path="benchmarks/tasks/02_dag_scheduler",
        difficulty="easy",
        category="Graph Algorithms",
        issue_description=(
            "`DAGScheduler.compile_plan()` uses an insertion-order queue instead of "
            "lexicographical min-heap tie-breaking among zero-in-degree tasks, and silently "
            "omits cyclic subgraphs instead of raising `CycleDetectedError(unscheduled_ids)` "
            "when `len(ordered) < len(self._nodes)`."
        ),
        ground_truth_symbols=["dag_scheduler/scheduler.py::DAGScheduler.compile_plan"],
    ),
    TaskSpec(
        task_id="03_token_bucket_limiter",
        title="TokenBucket idle refill burst-cap overflow & clock/cost guards",
        repo_rel_path="benchmarks/tasks/03_token_bucket_limiter",
        difficulty="medium",
        category="Rate Limiting & Floating-Point State",
        issue_description=(
            "In `TokenBucket._refill()` and `consume()`, replenishing tokens after a long idle "
            "interval allows `self._tokens` to grow past `self.capacity`, violating the burst cap."
        ),
        ground_truth_symbols=[
            "token_bucket_limiter/bucket.py::TokenBucket._refill",
            "token_bucket_limiter/bucket.py::TokenBucket.consume",
        ],
    ),
    TaskSpec(
        task_id="04_sql_query_builder",
        title="SelectQueryBuilder WHERE IN parameter collision & empty list SQL",
        repo_rel_path="benchmarks/tasks/04_sql_query_builder",
        difficulty="medium",
        category="Query Compilation",
        issue_description=(
            "Calling `SelectQueryBuilder.where_in()` (or `where_not_in()`) more than once "
            "restarts parameter numbering at `0` (`:in_0`, `:nin_0`), overwriting bound "
            "parameter values from earlier clauses."
        ),
        ground_truth_symbols=[
            "sql_query_builder/builder.py::SelectQueryBuilder.where_in",
            "sql_query_builder/builder.py::SelectQueryBuilder.where_not_in",
        ],
    ),
    TaskSpec(
        task_id="05_config_deep_merge",
        title="deep_merge_configs nested dict/list aliasing across environments",
        repo_rel_path="benchmarks/tasks/05_config_deep_merge",
        difficulty="easy",
        category="Immutability & Data Structures",
        issue_description=(
            "`deep_merge_configs(base, override)` only performs a shallow `dict(base)` copy "
            "and assigns `override` values directly, aliasing nested dicts and lists across "
            "merged profiles and mutating `base['plugins']` under `list_strategy='append_unique'`."
        ),
        ground_truth_symbols=["config_deep_merge/merger.py::deep_merge_configs"],
    ),
    TaskSpec(
        task_id="06_pagination_cursor",
        title="KeysetPaginator boundary duplicate & exact-page has_more lookahead",
        repo_rel_path="benchmarks/tasks/06_pagination_cursor",
        difficulty="easy",
        category="API Pagination",
        issue_description=(
            "`KeysetPaginator.paginate()` filters `rec.sort_tuple >= boundary` instead of "
            "strict `>`, duplicating the cursor boundary record on the next page, and checks "
            "`len(page_items) == limit` without `limit + 1` lookahead so `has_more` is `True` "
            "on an exact-multiple final page."
        ),
        ground_truth_symbols=["pagination_cursor/paginator.py::KeysetPaginator.paginate"],
    ),
    TaskSpec(
        task_id="07_event_bus_pubsub",
        title="EventBus unsubscribe-during-dispatch mutation & single-level wildcard",
        repo_rel_path="benchmarks/tasks/07_event_bus_pubsub",
        difficulty="easy",
        category="Concurrency & Pub/Sub Routing",
        issue_description=(
            "`EventBus.publish()` iterates over `self._subscriptions` directly while `once=True` "
            "or handler-invoked `unsubscribe()` deletes elements, skipping the next subscriber. "
            "Additionally, `topic_matches()` uses `fnmatchcase`, allowing single `*` in `orders.*` "
            "to match multi-segment topics like `orders.eu.paid` (only `**` should span multiple segments)."
        ),
        ground_truth_symbols=[
            "event_bus_pubsub/bus.py::EventBus.publish",
            "event_bus_pubsub/matcher.py::topic_matches",
        ],
    ),
    TaskSpec(
        task_id="08_retry_circuit_breaker",
        title="CircuitBreaker HALF_OPEN probe failure re-trip & max concurrent probes",
        repo_rel_path="benchmarks/tasks/08_retry_circuit_breaker",
        difficulty="medium",
        category="Distributed Resilience State Machine",
        issue_description=(
            "When `CircuitBreaker` transitions from `OPEN` to `HALF_OPEN` after cooldown, "
            "a single failed probe in `record_failure()` fails to immediately re-open the circuit "
            "because `_failure_count` was reset to 0 and compared against `failure_threshold`."
        ),
        ground_truth_symbols=[
            "retry_circuit_breaker/state_machine.py::CircuitBreaker.record_failure",
            "retry_circuit_breaker/state_machine.py::CircuitBreaker.allow_request",
        ],
    ),
    TaskSpec(
        task_id="09_interval_merger",
        title="merge_intervals strict-overlap touching boundary & input mutation",
        repo_rel_path="benchmarks/tasks/09_interval_merger",
        difficulty="medium",
        category="Computational Geometry / Timelines",
        issue_description=(
            "`merge_intervals(intervals, merge_adjacent=False)` merges touching intervals "
            "like `[1, 5)` and `[5, 8)` because it always checks `current.start <= prev.end` "
            "instead of honoring `merge_adjacent`."
        ),
        ground_truth_symbols=["interval_merger/timeline_merger.py::merge_intervals"],
    ),
    TaskSpec(
        task_id="10_ledger_reconciler",
        title="Multi-center largest-remainder rounding & credit-note reversal symmetry",
        repo_rel_path="benchmarks/tasks/10_ledger_reconciler",
        difficulty="hard",
        category="Financial Accounting Invariants",
        issue_description=(
            "`allocate_largest_remainder()` drops remainder cents via floor division, and "
            "posting a full credit reversal in `LedgerReconciler.post_credit_reversal()` leaves "
            "non-zero penny residuals across cost centers."
        ),
        ground_truth_symbols=[
            "ledger_reconciler/allocator.py::allocate_largest_remainder",
            "ledger_reconciler/reconciler.py::LedgerReconciler.post_credit_reversal",
        ],
    ),
    TaskSpec(
        task_id="11_dependency_injector",
        title="Scoped child container isolation & shared lazy singleton propagation",
        repo_rel_path="benchmarks/tasks/11_dependency_injector",
        difficulty="hard",
        category="Reflection & Object Lifetimes",
        issue_description=(
            "Child containers created via `Container.create_child_scope()` leak already-resolved "
            "parent `Scope.SCOPED` instances instead of isolating per child scope, while "
            "`Scope.SINGLETON` services first resolved inside a child scope are not shared back "
            "with the root container."
        ),
        ground_truth_symbols=[
            "dependency_injector/state_bank.py::InstanceBank._derive_standard_bank",
        ],
    ),
    TaskSpec(
        task_id="12_markdown_table_parser",
        title="GFM table row lexer escaped pipe vs multi-backtick code span",
        repo_rel_path="benchmarks/tasks/12_markdown_table_parser",
        difficulty="hard",
        category="Stateful Lexical Analysis",
        issue_description=(
            "`split_gfm_row()` splits table cells on backslash-escaped pipes `\\|` and raw pipes "
            "inside inline backtick code spans (including double-backtick spans containing single "
            "backticks and literal backslashes)."
        ),
        ground_truth_symbols=[
            "markdown_table_parser/tokenizer.py::split_gfm_row",
        ],
    ),
]


def load_all_tasks() -> list[TaskSpec]:
    """Return all 12 benchmark task specifications."""
    return list(BENCHMARK_TASKS)


def get_task_by_id(task_id: str) -> TaskSpec:
    """Lookup a benchmark `TaskSpec` by `task_id`."""
    for task in BENCHMARK_TASKS:
        if task.task_id == task_id:
            return task
    raise KeyError(f"Unknown benchmark task_id: {task_id!r}")


def resolve_task_repo_path(task: TaskSpec, project_root: Path | None = None) -> Path:
    """Resolve absolute directory path for `task`."""
    root = project_root or BENCHMARKS_ROOT.parent
    return (root / task.repo_rel_path).resolve()
