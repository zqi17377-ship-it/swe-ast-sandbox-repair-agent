"""Dual-Mode Repair LLM Backend: OpenAI-Compatible API Client + Context-Sensitive Simulator."""

from __future__ import annotations

import abc
import os
import re
from collections.abc import Callable

import httpx

from swe_repair_agent.ast_indexer import estimate_tokens
from swe_repair_agent.models import ChatMessage, LLMResponse, SearchReplaceEdit
from swe_repair_agent.patcher import parse_search_replace_blocks

_DIAGNOSIS_RE = re.compile(r"<diagnosis>(.*?)</diagnosis>", re.DOTALL | re.IGNORECASE)


def _extract_diagnosis(text: str) -> str:
    match = _DIAGNOSIS_RE.search(text)
    if match:
        return match.group(1).strip()
    first_para = text.split("<<<<<<<")[0].strip()
    return first_para[:400] if first_para else "Synthesizing targeted patch."


def format_sr_block(file_path: str, search: str, replace: str, diagnosis: str) -> str:
    """Format a structured `<diagnosis>` + `SEARCH/REPLACE` response string."""
    return (
        f"<diagnosis>\n{diagnosis}\n</diagnosis>\n\n"
        f"<<<<<<< FILE: {file_path}\n"
        f"<<<<<<< SEARCH\n"
        f"{search}\n"
        f"=======\n"
        f"{replace}\n"
        f">>>>>>> REPLACE"
    )


def format_multi_sr_blocks(
    blocks: list[tuple[str, str, str]], diagnosis: str
) -> str:
    """Format multiple `SEARCH/REPLACE` blocks into a single LLM response."""
    parts = [f"<diagnosis>\n{diagnosis}\n</diagnosis>"]
    for fp, search, replace in blocks:
        parts.append(
            f"<<<<<<< FILE: {fp}\n"
            f"<<<<<<< SEARCH\n{search}\n=======\n{replace}\n>>>>>>> REPLACE"
        )
    return "\n\n".join(parts)


class RepairLLM(abc.ABC):
    """Abstract interface for code-repair patch synthesis."""

    @abc.abstractmethod
    def generate_patch(self, messages: list[ChatMessage]) -> LLMResponse:
        """Generate diagnosis and structured `SEARCH/REPLACE` edits from prompt messages."""


class OpenAICompatibleLLM(RepairLLM):
    """Production LLM client speaking the OpenAI Chat Completions protocol via `httpx`."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        temperature: float = 0.0,
        timeout_sec: float = 60.0,
    ) -> None:
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is required for OpenAICompatibleLLM.")
        self.base_url = (
            base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        ).rstrip("/")
        self.model = model or os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        self.temperature = temperature
        self.timeout_sec = timeout_sec

    def generate_patch(self, messages: list[ChatMessage]) -> LLMResponse:
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=self.timeout_sec) as client:
            resp = client.post(
                f"{self.base_url}/chat/completions", json=payload, headers=headers
            )
            resp.raise_for_status()
            data = resp.json()

        content: str = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        edits = parse_search_replace_blocks(content)
        return LLMResponse(
            diagnosis=_extract_diagnosis(content),
            raw_content=content,
            edits=edits,
            prompt_tokens=int(
                usage.get(
                    "prompt_tokens",
                    sum(estimate_tokens(m.content) for m in messages),
                )
            ),
            completion_tokens=int(
                usage.get("completion_tokens", estimate_tokens(content))
            ),
        )


class MockRepairLLM(RepairLLM):
    """Stateful, context-visibility & traceback-driven code repair simulator.

    Inspects ONLY the prompt context and sandbox feedback supplied in `messages`:
    - If a target symbol was truncated out of the provided context window or missed
      by static AST localization, it cannot see or patch those lines.
    - On multi-condition bugs, Turn 1 repairs the primary issue symptom, and Turn 2+
      uses the actual `pytest` assertion traceback (or `ast.parse()` SyntaxError
      diagnostics) to self-heal edge cases.
    """

    def __init__(
        self,
        custom_responder: Callable[[list[ChatMessage]], str] | None = None,
    ) -> None:
        self._custom_responder = custom_responder

    def generate_patch(self, messages: list[ChatMessage]) -> LLMResponse:
        full_prompt = "\n\n".join(m.content for m in messages)
        prompt_tokens = sum(estimate_tokens(m.content) for m in messages)

        if self._custom_responder is not None:
            raw = self._custom_responder(messages)
        else:
            user_prompt = messages[-1].content if messages else full_prompt
            raw = self._synthesize_from_visible_context(user_prompt, full_prompt)

        edits: list[SearchReplaceEdit] = parse_search_replace_blocks(raw)
        return LLMResponse(
            diagnosis=_extract_diagnosis(raw),
            raw_content=raw,
            edits=edits,
            prompt_tokens=prompt_tokens,
            completion_tokens=estimate_tokens(raw),
        )

    def _synthesize_from_visible_context(
        self, latest_prompt: str, conversation_text: str
    ) -> str:
        # Split prompt into code context vs feedback sections so visibility checks only inspect code!
        if "## Sandbox Execution Feedback" in latest_prompt:
            code_part, feedback_part = latest_prompt.split(
                "## Sandbox Execution Feedback", 1
            )
        else:
            code_part, feedback_part = latest_prompt, ""

        # ------------------------------------------------------------------
        # Task 01: lru_ttl_cache
        # ------------------------------------------------------------------
        if "LRUTTLCache" in latest_prompt and "lru_ttl_cache/" in latest_prompt:
            store_get_target = (
                "        if is_expired(entry.expires_at, now):\n"
                "            # BUG: returns default on expired entry without deleting stale entry from _entries!\n"
                "            self.telemetry.record_miss(expired=True)\n"
                "            return default"
            )
            store_put_target = (
                "        # BUG: does not purge expired entries before evicting a live LRU entry at capacity!\n"
                "        if len(self._entries) >= self.config.max_size:"
            )
            expiry_target = (
                "    # BUG: uses strict `>` instead of `>=`, treating entries at exact deadline `now == expires_at` as still live\n"
                "    return now > expires_at"
            )

            # Turn 2+: store.py was already fixed (get/put failures gone); pytest traceback highlights exact TTL boundary
            if (
                "test_exact_ttl_boundary_is_treated_as_expired" in feedback_part
                and "test_expired_get_removes_stale_entry_from_len" not in feedback_part
                and expiry_target in code_part
            ):
                return format_sr_block(
                    "lru_ttl_cache/expiry.py",
                    expiry_target,
                    "    return now >= expires_at",
                    "Turn 1 resolved stale entry eviction in `store.py`, but `pytest` failed "
                    "`test_exact_ttl_boundary_is_treated_as_expired` at `now == 510.0`. "
                    "Inspecting `lru_ttl_cache/expiry.py::is_expired`, strict `now > expires_at` "
                    "treats entries at their exact deadline as live; changing to `now >= expires_at`.",
                )

            # Turn 1 (when store.py IS localized in context): fix get() and put()
            if store_get_target in code_part and store_put_target in code_part:
                return format_multi_sr_blocks(
                    [
                        (
                            "lru_ttl_cache/store.py",
                            store_get_target,
                            "        if is_expired(entry.expires_at, now):\n"
                            "            removed = self._entries.pop(key)\n"
                            "            if self.config.record_audit:\n"
                            "                self.audit.record(key, \"expired\", now, removed.created_at, removed.access_count)\n"
                            "            self.telemetry.record_miss(expired=True)\n"
                            "            return default",
                        ),
                        (
                            "lru_ttl_cache/store.py",
                            store_put_target,
                            "        if len(self._entries) >= self.config.max_size:\n"
                            "            self.purge_expired()\n"
                            "        if len(self._entries) >= self.config.max_size:",
                        ),
                    ],
                    "Localized `LRUTTLCache.get` and `LRUTTLCache.put` in `lru_ttl_cache/store.py`: "
                    "lazily pop expired keys during `get()` and invoke `self.purge_expired()` "
                    "before capacity eviction in `put()`.",
                )

            # Fallback when `store.py` was truncated out of Full-Context window!
            if expiry_target in code_part:
                return format_sr_block(
                    "lru_ttl_cache/expiry.py",
                    expiry_target,
                    "    return now >= expires_at",
                    "`lru_ttl_cache/store.py` is truncated from the context window; applying "
                    "best-effort boundary fix in visible `lru_ttl_cache/expiry.py`.",
                )

        # ------------------------------------------------------------------
        # Task 02: dag_scheduler
        # ------------------------------------------------------------------
        if "DAGScheduler" in latest_prompt and "dag_scheduler/" in latest_prompt:
            sched_target = (
                "        # BUG 1: uses insertion-order deque instead of min-heap lexicographical tie-breaking!\n"
                "        # BUG 2: silently drops remaining cycle nodes instead of raising CycleDetectedError!\n"
                "        ready = deque(tid for tid, deg in in_degree.items() if deg == 0)\n"
                "        ordered: list[str] = []\n\n"
                "        while ready:\n"
                "            current = ready.popleft()\n"
                "            ordered.append(current)\n"
                "            for nxt in dependents[current]:\n"
                "                in_degree[nxt] -= 1\n"
                "                if in_degree[nxt] == 0:\n"
                "                    ready.append(nxt)"
            )
            if sched_target in code_part:
                return format_sr_block(
                    "dag_scheduler/scheduler.py",
                    sched_target,
                    "        ready: list[str] = sorted(tid for tid, deg in in_degree.items() if deg == 0)\n"
                    "        heapq.heapify(ready)\n"
                    "        ordered: list[str] = []\n\n"
                    "        while ready:\n"
                    "            current = heapq.heappop(ready)\n"
                    "            ordered.append(current)\n"
                    "            for nxt in dependents[current]:\n"
                    "                in_degree[nxt] -= 1\n"
                    "                if in_degree[nxt] == 0:\n"
                    "                    heapq.heappush(ready, nxt)\n\n"
                    "        if len(ordered) < len(self._nodes):\n"
                    "            scheduled = set(ordered)\n"
                    "            cycle_ids = [tid for tid in self._nodes if tid not in scheduled]\n"
                    "            raise CycleDetectedError(cycle_ids)",
                    "Replaced FIFO `deque` with `heapq` lexicographical min-heap in "
                    "`DAGScheduler.compile_plan` and raised `CycleDetectedError` when unvisited "
                    "nodes remain.",
                )

        # ------------------------------------------------------------------
        # Task 03: token_bucket_limiter
        # ------------------------------------------------------------------
        if "TokenBucket" in latest_prompt and "token_bucket_limiter/" in latest_prompt:
            refill_orig = (
                "        # BUG 1: does not clamp `self._tokens` to `self.capacity` burst limit!\n"
                "        # BUG 2: does not guard against backward clock skew (`now < self._last_refill`), draining tokens!\n"
                "        elapsed = now - self._last_refill\n"
                "        self._tokens = self._tokens + elapsed * self.refill_rate\n"
                "        self._last_refill = now"
            )
            refill_turn1 = (
                "        elapsed = now - self._last_refill\n"
                "        self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_rate)\n"
                "        self._last_refill = now"
            )
            consume_orig = (
                "        # BUG 3: missing validation for non-positive cost (`cost <= 0`)!\n"
                "        ts = self._clock() if now is None else now"
            )

            # Turn 2+: feedback reveals backward clock skew & non-positive cost edge cases
            if (
                ("test_backward_clock_skew" in feedback_part or "test_non_positive_cost" in feedback_part)
                and refill_turn1 in code_part
                and consume_orig in code_part
            ):
                return format_multi_sr_blocks(
                    [
                        (
                            "token_bucket_limiter/bucket.py",
                            refill_turn1,
                            "        if now <= self._last_refill:\n"
                            "            return\n"
                            "        elapsed = now - self._last_refill\n"
                            "        self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_rate)\n"
                            "        self._last_refill = now",
                        ),
                        (
                            "token_bucket_limiter/bucket.py",
                            consume_orig,
                            "        if cost <= 0:\n"
                            "            raise ValueError(\"cost must be strictly positive.\")\n"
                            "        ts = self._clock() if now is None else now",
                        ),
                    ],
                    "Pytest feedback exposed two boundary regressions: non-monotonic `now < _last_refill` "
                    "draining tokens and non-positive `cost <= 0`. Guarding `_refill` against backward "
                    "timestamps and validating `cost > 0` in `consume()`.",
                )

            if refill_orig in code_part:
                return format_sr_block(
                    "token_bucket_limiter/bucket.py",
                    refill_orig,
                    refill_turn1,
                    "Clamping replenished tokens to `self.capacity` inside `TokenBucket._refill()`.",
                )

        # ------------------------------------------------------------------
        # Task 04: sql_query_builder
        # ------------------------------------------------------------------
        if "SelectQueryBuilder" in latest_prompt and "sql_query_builder/" in latest_prompt:
            win_orig = (
                "        # BUG 1: resets index `i` from 0 on each call, colliding `:in_0` across multiple where_in() calls!\n"
                "        # BUG 2: empty `values` emits invalid SQL `col IN ()` instead of constant `1 = 0`!\n"
                "        placeholders: list[str] = []\n"
                "        for i, val in enumerate(values):\n"
                "            key = f\"in_{i}\"\n"
                "            self._params[key] = val\n"
                "            placeholders.append(f\":{key}\")\n"
                "        self._where_clauses.append(f\"{col} IN ({', '.join(placeholders)})\")"
            )
            wnin_orig = (
                "        # Same parameter-collision & empty-list (`1 = 1`) bug!\n"
                "        placeholders: list[str] = []\n"
                "        for i, val in enumerate(values):\n"
                "            key = f\"nin_{i}\"\n"
                "            self._params[key] = val\n"
                "            placeholders.append(f\":{key}\")\n"
                "        self._where_clauses.append(f\"{col} NOT IN ({', '.join(placeholders)})\")"
            )
            win_turn1 = (
                "        placeholders = [self._alloc_param(\"in\", val) for val in values]\n"
                "        self._where_clauses.append(f\"{col} IN ({', '.join(placeholders)})\")"
            )
            wnin_turn1 = (
                "        placeholders = [self._alloc_param(\"nin\", val) for val in values]\n"
                "        self._where_clauses.append(f\"{col} NOT IN ({', '.join(placeholders)})\")"
            )

            # Turn 2+: empty_list ANSI SQL `IN ()` / `NOT IN ()` assertion or OperationalError
            if (
                "OperationalError" in feedback_part
                or "empty_list" in feedback_part
                or "IN ()" in feedback_part
            ) and (win_turn1 in code_part or wnin_turn1 in code_part):
                blocks: list[tuple[str, str, str]] = []
                if win_turn1 in code_part:
                    blocks.append(
                        (
                            "sql_query_builder/builder.py",
                            win_turn1,
                            "        if not values:\n"
                            "            self._where_clauses.append(\"1 = 0\")\n"
                            "            return self\n"
                            "        placeholders = [self._alloc_param(\"in\", val) for val in values]\n"
                            "        self._where_clauses.append(f\"{col} IN ({', '.join(placeholders)})\")",
                        )
                    )
                if wnin_turn1 in code_part:
                    blocks.append(
                        (
                            "sql_query_builder/builder.py",
                            wnin_turn1,
                            "        if not values:\n"
                            "            self._where_clauses.append(\"1 = 1\")\n"
                            "            return self\n"
                            "        placeholders = [self._alloc_param(\"nin\", val) for val in values]\n"
                            "        self._where_clauses.append(f\"{col} NOT IN ({', '.join(placeholders)})\")",
                        )
                    )
                return format_multi_sr_blocks(
                    blocks,
                    "Empty `IN ()` / `NOT IN ()` failed ANSI SQL portability assertions. "
                    "Short-circuiting empty `where_in` to `1 = 0` and empty `where_not_in` to `1 = 1`.",
                )

            if win_orig in code_part and wnin_orig in code_part:
                return format_multi_sr_blocks(
                    [
                        ("sql_query_builder/builder.py", win_orig, win_turn1),
                        ("sql_query_builder/builder.py", wnin_orig, wnin_turn1),
                    ],
                    "Allocated monotonic bind parameter names via `self._alloc_param()` in "
                    "`where_in` and `where_not_in` to prevent key collisions.",
                )

        # ------------------------------------------------------------------
        # Task 05: config_deep_merge
        # ------------------------------------------------------------------
        if "deep_merge_configs" in latest_prompt and "config_deep_merge/" in latest_prompt:
            merge_orig = (
                "    # BUG: shallow `dict(base)` aliases nested dicts and lists from `base` and `override`!\n"
                "    merged: dict[str, Any] = dict(base)\n"
                "    for key, over_val in override.items():\n"
                "        if key in merged and isinstance(merged[key], dict) and isinstance(over_val, dict):\n"
                "            merged[key] = deep_merge_configs(\n"
                "                merged[key], over_val, list_strategy=list_strategy\n"
                "            )\n"
                "        elif (\n"
                "            list_strategy == \"append_unique\"\n"
                "            and key in merged\n"
                "            and isinstance(merged[key], list)\n"
                "            and isinstance(over_val, list)\n"
                "        ):\n"
                "            combined = merged[key]\n"
                "            for item in over_val:\n"
                "                if item not in combined:\n"
                "                    combined.append(item)\n"
                "            merged[key] = combined\n"
                "        else:\n"
                "            merged[key] = over_val"
            )
            if merge_orig in code_part:
                return format_sr_block(
                    "config_deep_merge/merger.py",
                    merge_orig,
                    "    merged: dict[str, Any] = copy.deepcopy(base)\n"
                    "    for key, over_val in override.items():\n"
                    "        if key in merged and isinstance(merged[key], dict) and isinstance(over_val, dict):\n"
                    "            merged[key] = deep_merge_configs(\n"
                    "                merged[key], over_val, list_strategy=list_strategy\n"
                    "            )\n"
                    "        elif (\n"
                    "            list_strategy == \"append_unique\"\n"
                    "            and key in merged\n"
                    "            and isinstance(merged[key], list)\n"
                    "            and isinstance(over_val, list)\n"
                    "        ):\n"
                    "            combined = list(merged[key])\n"
                    "            for item in over_val:\n"
                    "                if item not in combined:\n"
                    "                    combined.append(copy.deepcopy(item))\n"
                    "            merged[key] = combined\n"
                    "        else:\n"
                    "            merged[key] = copy.deepcopy(over_val)",
                    "Deep-copying `base` and `override` subtrees in `deep_merge_configs` so nested "
                    "dicts and lists never alias across environments.",
                )

        # ------------------------------------------------------------------
        # Task 06: pagination_cursor
        # ------------------------------------------------------------------
        if "KeysetPaginator" in latest_prompt and "pagination_cursor/" in latest_prompt:
            pag_orig = (
                "            # BUG 1: uses `>=` instead of strict `>`, duplicating boundary item on next page!\n"
                "            ordered = [rec for rec in ordered if rec.sort_tuple >= boundary]\n\n"
                "        # BUG 2: slices `ordered[:limit]` without `limit + 1` lookahead, reporting `has_more=True`\n"
                "        # even when `len(ordered) == limit` (exact final page)!\n"
                "        page_items = ordered[:limit]\n"
                "        has_more = len(page_items) == limit"
            )
            if pag_orig in code_part:
                return format_sr_block(
                    "pagination_cursor/paginator.py",
                    pag_orig,
                    "            ordered = [rec for rec in ordered if rec.sort_tuple > boundary]\n\n"
                    "        window = ordered[: limit + 1]\n"
                    "        has_more = len(window) > limit\n"
                    "        page_items = window[:limit]",
                    "Localized `KeysetPaginator.paginate` in `pagination_cursor/paginator.py`: "
                    "enforced strict `>` cursor progression and `limit + 1` lookahead slicing.",
                )
            # Truncated in Full-Context!
            codec_fallback = "    padded = token.strip()"
            if codec_fallback in code_part:
                return format_sr_block(
                    "pagination_cursor/codec.py",
                    codec_fallback,
                    "    padded = token.strip()",
                    "`pagination_cursor/paginator.py` was truncated out of the context window; "
                    "cannot see `KeysetPaginator.paginate` body.",
                )

        # ------------------------------------------------------------------
        # Task 07: event_bus_pubsub
        # ------------------------------------------------------------------
        if "EventBus" in latest_prompt and "event_bus_pubsub/" in latest_prompt:
            bus_orig = (
                "        # BUG: iterates directly over `self._subscriptions` while `once=True` or handler-triggered\n"
                "        # `unsubscribe()` mutates `self._subscriptions`, skipping the immediately following subscriber!\n"
                "        for sub in self._subscriptions:"
            )
            match_orig = (
                "    # BUG: `fnmatchcase` lets single `*` cross `.` boundaries, matching `orders.eu.paid` against `orders.*`!\n"
                "    return fnmatch.fnmatchcase(topic, pattern)"
            )
            if bus_orig in code_part and match_orig in code_part:
                return format_multi_sr_blocks(
                    [
                        (
                            "event_bus_pubsub/bus.py",
                            bus_orig,
                            "        for sub in list(self._subscriptions):",
                        ),
                        (
                            "event_bus_pubsub/matcher.py",
                            match_orig,
                            "    pat_parts = pattern.split(\".\")\n"
                            "    top_parts = topic.split(\".\")\n\n"
                            "    def _match(pi: int, ti: int) -> bool:\n"
                            "        if pi == len(pat_parts) and ti == len(top_parts):\n"
                            "            return True\n"
                            "        if pi == len(pat_parts):\n"
                            "            return False\n"
                            "        if pat_parts[pi] == \"**\":\n"
                            "            return _match(pi + 1, ti) or (ti < len(top_parts) and _match(pi, ti + 1))\n"
                            "        if ti == len(top_parts):\n"
                            "            return False\n"
                            "        if pat_parts[pi] == \"*\" or pat_parts[pi] == top_parts[ti]:\n"
                            "            return _match(pi + 1, ti + 1)\n"
                            "        return False\n\n"
                            "    return _match(0, 0)",
                        ),
                    ],
                    "Snapshotted `list(self._subscriptions)` during `EventBus.publish()` and "
                    "implemented segment-aware `*` vs `**` hierarchical matching in `topic_matches()`.",
                )

        # ------------------------------------------------------------------
        # Task 08: retry_circuit_breaker
        # ------------------------------------------------------------------
        if "CircuitBreaker" in latest_prompt and "retry_circuit_breaker/" in latest_prompt:
            fail_orig = (
                "        # BUG 1 continued: requires `failure_threshold` failures even when in `HALF_OPEN`!\n"
                "        if self._failure_count >= self.failure_threshold:"
            )
            fail_turn1 = (
                "        if self._state == BreakerState.HALF_OPEN or self._failure_count >= self.failure_threshold:"
            )
            allow_orig = (
                "        # BUG 2: in HALF_OPEN, fails to enforce `self._half_open_calls < self.half_open_max_calls`,\n"
                "        # letting unlimited concurrent probe requests flood the recovering downstream!\n"
                "        if self._state == BreakerState.HALF_OPEN:\n"
                "            self._half_open_calls += 1"
            )

            # Turn 2+: enforce half_open_max_calls after pytest feedback
            if (
                "test_half_open_enforces_max_concurrent_probe_calls" in feedback_part
                and fail_turn1 in code_part
                and allow_orig in code_part
            ):
                return format_sr_block(
                    "retry_circuit_breaker/state_machine.py",
                    allow_orig,
                    "        if self._state == BreakerState.HALF_OPEN:\n"
                    "            if self._half_open_calls >= self.half_open_max_calls:\n"
                    "                raise CircuitOpenError(self.service_name, retry_after_sec=self.recovery_timeout_sec)\n"
                    "            self._half_open_calls += 1",
                    "Turn 1 fixed immediate `HALF_OPEN -> OPEN` re-trip, and `pytest` revealed "
                    "missing concurrency cap in `allow_request()`. Rejecting excess probes with "
                    "`CircuitOpenError` when `_half_open_calls >= half_open_max_calls`.",
                )

            if fail_orig in code_part:
                return format_sr_block(
                    "retry_circuit_breaker/state_machine.py",
                    fail_orig,
                    fail_turn1,
                    "Immediately re-opening `CircuitBreaker` in `record_failure()` when a probe "
                    "fails in `BreakerState.HALF_OPEN`.",
                )

            # Truncated in Full-Context!
            backoff_line = "    clamped_jitter = max(-0.5, min(0.5, jitter_ratio))"
            if backoff_line in code_part:
                return format_sr_block(
                    "retry_circuit_breaker/backoff.py",
                    backoff_line,
                    "    clamped_jitter = max(-0.5, min(0.5, float(jitter_ratio)))",
                    "`retry_circuit_breaker/state_machine.py` was truncated out of context; "
                    "`CircuitBreaker` state machine methods are not visible.",
                )

        # ------------------------------------------------------------------
        # Task 09: interval_merger (Turn 1 boundary -> Turn 2 SyntaxError rollback -> Turn 3 full fix)
        # ------------------------------------------------------------------
        if "merge_intervals" in latest_prompt and "interval_merger/" in latest_prompt:
            sort_bug = (
                "    # BUG 1: mutates caller's `intervals` list in place via `.sort()`!\n"
                "    intervals.sort(key=lambda iv: (iv.start, iv.end))\n\n"
                "    merged: list[Interval] = [intervals[0]]\n"
                "    for current in intervals[1:]:"
            )
            adj_bug = (
                "        # BUG 2: always merges touching intervals (`current.start <= prev.end`) even when\n"
                "        # `merge_adjacent=False` (where `[1, 5)` and `[5, 9)` should remain separate)!\n"
                "        if current.start <= prev.end:"
            )
            adj_fixed = (
                "        should_merge = current.start <= prev.end if merge_adjacent else current.start < prev.end\n"
                "        if should_merge:"
            )

            # Turn 3: after AST pre-commit guard rolled back Turn 2's SyntaxError!
            if "SyntaxError" in feedback_part and sort_bug in code_part and adj_fixed in code_part:
                return format_sr_block(
                    "interval_merger/timeline_merger.py",
                    sort_bug,
                    "    ordered = sorted(intervals, key=lambda iv: (iv.start, iv.end))\n\n"
                    "    merged: list[Interval] = [ordered[0]]\n"
                    "    for current in ordered[1:]:",
                    "Recovered from Turn 2 `SyntaxError` (caught and rolled back by AST syntax guard): "
                    "balanced parentheses in `sorted(intervals, key=...)` to avoid mutating caller's list.",
                )

            # Turn 2: sees caller list mutation failure, emits candidate with accidental missing `)`
            if (
                "test_does_not_mutate_caller_unsorted_input_list" in feedback_part
                and sort_bug in code_part
                and adj_fixed in code_part
            ):
                return format_sr_block(
                    "interval_merger/timeline_merger.py",
                    sort_bug,
                    "    ordered = sorted(intervals, key=lambda iv: (iv.start, iv.end)\n\n"
                    "    merged: list[Interval] = [ordered[0]]\n"
                    "    for current in ordered[1:]:",
                    "Pytest caught in-place `.sort()` mutating caller's input list; switching to `sorted()`.",
                )

            # Turn 1: fix merge_adjacent comparison
            if adj_bug in code_part:
                return format_sr_block(
                    "interval_merger/timeline_merger.py",
                    adj_bug,
                    adj_fixed,
                    "Distinguishing inclusive `current.start <= prev.end` when `merge_adjacent=True` "
                    "from strict overlap `current.start < prev.end` when `merge_adjacent=False`.",
                )

            # Truncated in Full-Context!
            queries_line = "    cursor = window_start"
            if queries_line in code_part:
                return format_sr_block(
                    "interval_merger/queries.py",
                    queries_line,
                    "    cursor = int(window_start)",
                    "`interval_merger/timeline_merger.py` was truncated from the unpruned context window.",
                )

        # ------------------------------------------------------------------
        # Task 10: ledger_reconciler (Hard Case 1: Cross-Module Invariant Oscillation)
        # ------------------------------------------------------------------
        if "allocate_largest_remainder" in latest_prompt and "ledger_reconciler/" in latest_prompt:
            alloc_orig = (
                "    # BUG: floors each share via `//` and discards the remainder pennies completely,\n"
                "    # AND Python's floor division on negative `amount_cents` rounds toward -infinity!\n"
                "    return [(amount_cents * w) // total_weight for w in weights]"
            )
            alloc_t1 = (
                "    quotients = [(amount_cents * w) // total_weight for w in weights]\n"
                "    rem = amount_cents - sum(quotients)\n"
                "    order = sorted(range(len(weights)), key=lambda i: -((amount_cents * weights[i]) % total_weight))\n"
                "    for idx in order[:rem]:\n"
                "        quotients[idx] += 1\n"
                "    return quotients"
            )
            alloc_t2 = (
                "    sign = -1 if amount_cents < 0 else 1\n"
                "    mag = abs(amount_cents)\n"
                "    quotients = [(mag * w) // total_weight for w in weights]\n"
                "    rem = mag - sum(quotients)\n"
                "    order = sorted(range(len(weights)), key=lambda i: (-((mag * weights[i]) % total_weight), i))\n"
                "    for idx in order[:rem]:\n"
                "        quotients[idx] += 1\n"
                "    return [sign * q for q in quotients]"
            )
            rec_orig = "        total_fee = (signed_gross * fee_bps + 5000) // 10000"
            rec_t3 = "        total_fee = -((gross_cents * fee_bps + 5000) // 10000)"

            if rec_t3 in code_part:
                return format_sr_block(
                    "ledger_reconciler/reconciler.py",
                    rec_t3,
                    "        total_fee = -((gross_cents * fee_bps + 4999) // 10000)",
                    "Attempting half-down fee rounding adjustment to resolve 1-cent cost-center residual.",
                )
            if alloc_t2 in code_part and rec_orig in code_part:
                return format_sr_block(
                    "ledger_reconciler/reconciler.py",
                    rec_orig,
                    rec_t3,
                    "Sign-symmetric allocation fixed `allocator.py`, but credit reversal fee rounding "
                    "still drifts; negating positive half-up fee calculation in `reconciler.py`.",
                )
            if alloc_t1 in code_part:
                return format_sr_block(
                    "ledger_reconciler/allocator.py",
                    alloc_t1,
                    alloc_t2,
                    "Pytest showed negative `amount_cents` remainder mismatch due to floor division; "
                    "switching `allocate_largest_remainder` to magnitude + sign symmetry.",
                )
            if alloc_orig in code_part:
                return format_sr_block(
                    "ledger_reconciler/allocator.py",
                    alloc_orig,
                    alloc_t1,
                    "Implemented Hamilton largest-remainder penny distribution in `allocate_largest_remainder`.",
                )

        # ------------------------------------------------------------------
        # Task 11: dependency_injector (Hard Case 2: Dynamic Dispatch Call-Graph Gap)
        # ------------------------------------------------------------------
        if "Container" in latest_prompt and "dependency_injector/" in latest_prompt:
            # Note: `state_bank.py::InstanceBank._derive_standard_bank` is hidden behind `getattr`!
            # Only patch it if its exact body WERE somehow visible in code_part!
            bank_target = (
                "        return InstanceBank(\n"
                "            root_cells=dict(self._root_cells),\n"
                "            local_slots=dict(self._local_slots),\n"
                "        )"
            )
            if bank_target in code_part:
                return format_sr_block(
                    "dependency_injector/state_bank.py",
                    bank_target,
                    "        return InstanceBank(\n"
                    "            root_cells=self._root_cells,\n"
                    "            local_slots={},\n"
                    "        )",
                    "Sharing `_root_cells` reference and resetting `local_slots` in `_derive_standard_bank`.",
                )

            # Realistic local attempt on visible `resolver.py` when `state_bank.py` is unseen:
            res_t1 = (
                "        hook_name = f\"_derive_{mode}_bank\"\n"
                "        derive_fn = getattr(self._bank, hook_name)\n"
                "        child_bank = derive_fn()\n"
                "        return Container(_catalog=self._catalog.clone(), _bank=child_bank)"
            )
            res_t2 = (
                "        hook_name = f\"_derive_{mode}_bank\"\n"
                "        derive_fn = getattr(self._bank, hook_name)\n"
                "        child_bank = derive_fn()\n"
                "        return Container(_catalog=self._catalog, _bank=child_bank)"
            )
            if res_t1 in code_part:
                return format_sr_block(
                    "dependency_injector/resolver.py",
                    res_t1,
                    res_t2,
                    "`InstanceBank` internals are dynamically dispatched via `getattr` and not visible "
                    "in localized excerpts; attempting to share `self._catalog` across child container.",
                )
            if res_t2 in code_part:
                return format_sr_block(
                    "dependency_injector/resolver.py",
                    res_t2,
                    "        return Container(_catalog=self._catalog)",
                    "Attempting fresh default `InstanceBank()` on child scope creation (isolates scoped "
                    "services, though root singleton link inside `InstanceBank` remains unexposed).",
                )

        # ------------------------------------------------------------------
        # Task 12: markdown_table_parser (Hard Case 3: Lexer Specification Regression)
        # ------------------------------------------------------------------
        if "split_gfm_row" in latest_prompt and "markdown_table_parser/" in latest_prompt:
            tok_orig = (
                "    # BUG: naive `.split(\"|\")` splits inside backtick code spans (e.g. `` `a | b` `` and\n"
                "    # multi-backtick `` ``a | ` | b`` ``) AND splits on backslash-escaped `\\|` pipes!\n"
                "    return [cell.strip() for cell in stripped.split(\"|\")]"
            )
            tok_t1 = (
                "    cells: list[str] = []\n"
                "    buf: list[str] = []\n"
                "    in_code = False\n"
                "    i = 0\n"
                "    while i < len(stripped):\n"
                "        ch = stripped[i]\n"
                "        if ch == \"\\\\\" and i + 1 < len(stripped) and stripped[i + 1] == \"|\":\n"
                "            buf.append(\"|\")\n"
                "            i += 2\n"
                "            continue\n"
                "        if ch == \"`\":\n"
                "            in_code = not in_code\n"
                "        if ch == \"|\" and not in_code:\n"
                "            cells.append(\"\".join(buf).strip())\n"
                "            buf.clear()\n"
                "        else:\n"
                "            buf.append(ch)\n"
                "        i += 1\n"
                "    cells.append(\"\".join(buf).strip())\n"
                "    return cells"
            )
            tok_t2 = tok_t1.replace(
                "        if ch == \"\\\\\" and i + 1 < len(stripped) and stripped[i + 1] == \"|\":\n"
                "            buf.append(\"|\")",
                "        if ch == \"\\\\\" and i + 1 < len(stripped) and stripped[i + 1] == \"|\":\n"
                "            buf.append(r\"\\|\" if in_code else \"|\")",
            )
            if tok_t2 in code_part:
                return format_sr_block(
                    "markdown_table_parser/tokenizer.py",
                    "        if ch == \"`\":\n            in_code = not in_code",
                    "        if ch == \"`\" and (i == 0 or stripped[i - 1] != \"`\"):  # multi-backtick toggle attempt\n"
                    "            in_code = not in_code",
                    "Attempting heuristic multi-backtick delimiter toggle without full CommonMark "
                    "matching-run-length lookahead.",
                )
            if tok_t1 in code_part:
                return format_sr_block(
                    "markdown_table_parser/tokenizer.py",
                    tok_t1,
                    tok_t2,
                    "Preserving literal `\\|` inside `in_code` spans per GFM code-span escape rules.",
                )
            if tok_orig in code_part:
                return format_sr_block(
                    "markdown_table_parser/tokenizer.py",
                    tok_orig,
                    tok_t1,
                    "Replaced `.split(\"|\")` with single-pass lexer tracking `in_code` backticks "
                    "and `\\|` escapes.",
                )

        return (
            "<diagnosis>Unable to locate matching target snippet in visible context.</diagnosis>"
        )


def create_repair_llm(prefer_live: bool = False) -> RepairLLM:
    """Create `OpenAICompatibleLLM` when `prefer_live` and `OPENAI_API_KEY` is set, else `MockRepairLLM`."""
    if prefer_live and os.environ.get("OPENAI_API_KEY", "").strip():
        return OpenAICompatibleLLM()
    return MockRepairLLM()
