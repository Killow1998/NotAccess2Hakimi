"""Model catalog invariants shared by discovery and adapters."""

from hakimi_proxy.adapters.aistudio import SUPPORTED_MODELS as AISTUDIO_ADAPTER_MODELS
from hakimi_proxy.adapters.antigravity import SUPPORTED_MODELS as ANTIGRAVITY_ADAPTER_MODELS
from hakimi_proxy.model_catalog import (
    AISTUDIO_MODELS,
    ALL_MODELS,
    ANTIGRAVITY_MODELS,
    list_model_discovery_entries,
    resolve_antigravity_model,
)


def test_adapters_use_the_shared_catalog():
    assert AISTUDIO_ADAPTER_MODELS is AISTUDIO_MODELS
    assert ANTIGRAVITY_ADAPTER_MODELS is ANTIGRAVITY_MODELS
    assert ALL_MODELS == AISTUDIO_MODELS | ANTIGRAVITY_MODELS


def test_discovery_catalog_is_sorted_and_complete():
    entries = list_model_discovery_entries()
    assert [entry["id"] for entry in entries] == sorted(ALL_MODELS)
    assert len(entries) == len(ALL_MODELS)


def test_antigravity_alias_is_catalog_owned():
    assert resolve_antigravity_model("Gemini-3.8-Flash") == "gemini-3.8-flash-tiered"
    assert resolve_antigravity_model("gemini-3.8-flash-tiered") == "gemini-3.8-flash-tiered"
    assert resolve_antigravity_model("Gemini-3.7-Flash") == "gemini-3.7-flash-tiered"
    assert resolve_antigravity_model("gemini-3.7-flash-tiered") == "gemini-3.7-flash-tiered"


def test_gemini_38_flash_has_official_limits_and_reasoning_levels():
    entry = next(item for item in list_model_discovery_entries() if item["id"] == "gemini-3.8-flash")
    assert entry["context_window"] == 1_048_576
    assert entry["max_input_tokens"] == 1_048_576
    assert entry["output_limit"] == 65_536
    assert entry["reasoning_levels"] == ["low", "medium", "high"]
    assert entry["capability_sources"]["context_window"]["source"] == "official"


def test_unknown_model_limits_are_not_fabricated():
    entry = next(
        item for item in list_model_discovery_entries()
        if item["id"] == "gemini-3-flash-agent"
    )
    assert "context_window" not in entry
    assert "reasoning_levels" not in entry
    assert entry["capability_sources"]["context_window"]["source"] == "unknown"
