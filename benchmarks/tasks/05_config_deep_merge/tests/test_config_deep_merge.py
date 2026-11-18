"""Tests verifying zero cross-environment aliasing in deep_merge_configs."""

from __future__ import annotations

from config_deep_merge import EnvironmentProfileBuilder, deep_merge_configs


def test_nested_dict_mutation_does_not_alias_base() -> None:
    base = {
        "database": {"host": "localhost", "pool": {"min": 2, "max": 10}},
        "features": {"audit": True, "allowlist": ["internal"]},
    }
    override = {"database": {"host": "prod-db.internal"}}

    merged = deep_merge_configs(base, override)
    merged["database"]["pool"]["max"] = 50
    merged["features"]["allowlist"].append("partner")

    assert base["database"]["pool"]["max"] == 10
    assert base["features"]["allowlist"] == ["internal"]


def test_override_nested_structures_are_not_aliased_into_result() -> None:
    base = {"service": {"timeout": 5}}
    override = {"service": {"headers": {"X-Env": "staging"}, "tags": ["v1"]}}

    merged = deep_merge_configs(base, override)
    override["service"]["headers"]["X-Env"] = "mutated"
    override["service"]["tags"].append("mutated")

    assert merged["service"]["headers"]["X-Env"] == "staging"
    assert merged["service"]["tags"] == ["v1"]


def test_append_unique_list_strategy_does_not_mutate_base_list() -> None:
    base = {"plugins": ["auth", "metrics"]}
    staging = deep_merge_configs(
        base, {"plugins": ["metrics", "tracing"]}, list_strategy="append_unique"
    )
    prod = deep_merge_configs(
        base, {"plugins": ["waf"]}, list_strategy="append_unique"
    )

    assert base["plugins"] == ["auth", "metrics"]
    assert staging["plugins"] == ["auth", "metrics", "tracing"]
    assert prod["plugins"] == ["auth", "metrics", "waf"]


def test_environment_profile_builder_isolates_profiles() -> None:
    builder = EnvironmentProfileBuilder(
        {"cache": {"redis": {"db": 0, "nodes": ["n1"]}}}
    )
    builder.register_overlay("dev", {"cache": {"redis": {"db": 1}}})
    p1 = builder.build_profile("dev")
    p1["cache"]["redis"]["nodes"].append("injected")

    p2 = builder.build_profile("dev")
    assert p2["cache"]["redis"]["nodes"] == ["n1"]
