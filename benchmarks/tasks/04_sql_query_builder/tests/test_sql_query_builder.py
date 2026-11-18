"""Tests for SelectQueryBuilder parameter non-collision, empty IN predicates, and SQLite execution."""

from __future__ import annotations

import sqlite3

from sql_query_builder import SelectQueryBuilder


def _seed_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE orders (id INTEGER PRIMARY KEY, status TEXT, tier TEXT, amount INTEGER)"
    )
    conn.executemany(
        "INSERT INTO orders (id, status, tier, amount) VALUES (?, ?, ?, ?)",
        [
            (1, "open", "pro", 120),
            (2, "pending", "free", 40),
            (3, "open", "enterprise", 500),
            (4, "cancelled", "pro", 90),
        ],
    )
    return conn


def test_multiple_where_in_clauses_do_not_collide_parameters() -> None:
    conn = _seed_db()
    q = (
        SelectQueryBuilder("orders", columns=["id", "status", "tier"])
        .where_in("status", ["open", "pending"])
        .where_in("tier", ["pro"])
        .order_by("id")
        .build()
    )
    rows = conn.execute(q.sql, q.params).fetchall()
    assert rows == [(1, "open", "pro")]
    assert len(q.params) == 3


def test_multiple_where_not_in_clauses_preserve_distinct_params() -> None:
    conn = _seed_db()
    q = (
        SelectQueryBuilder("orders", columns=["id"])
        .where_not_in("status", ["cancelled"])
        .where_not_in("tier", ["free"])
        .order_by("id")
        .build()
    )
    rows = conn.execute(q.sql, q.params).fetchall()
    assert [r[0] for r in rows] == [1, 3]


def test_where_in_empty_list_compiles_valid_false_predicate() -> None:
    conn = _seed_db()
    q = (
        SelectQueryBuilder("orders", columns=["id"])
        .where_eq("tier", "pro")
        .where_in("status", [])
        .build()
    )
    rows = conn.execute(q.sql, q.params).fetchall()
    assert "IN ()" not in q.sql, "Empty WHERE IN must not emit non-portable ANSI SQL `IN ()`"
    assert rows == []


def test_where_not_in_empty_list_compiles_valid_true_predicate() -> None:
    conn = _seed_db()
    q = (
        SelectQueryBuilder("orders", columns=["id"])
        .where_eq("tier", "pro")
        .where_not_in("status", [])
        .order_by("id")
        .build()
    )
    rows = conn.execute(q.sql, q.params).fetchall()
    assert "NOT IN ()" not in q.sql, "Empty WHERE NOT IN must not emit non-portable ANSI SQL `NOT IN ()`"
    assert [r[0] for r in rows] == [1, 4]
