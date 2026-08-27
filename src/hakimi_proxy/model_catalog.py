"""Provider model catalog and OpenAI-compatible discovery metadata.

Only publish model-specific limits that have an authoritative or observed
source.  Gateway protocol capabilities describe behavior implemented by NA2H
itself and are deliberately conservative across both upstream adapters.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


AISTUDIO_MODELS: frozenset[str] = frozenset({
    "gemini-3.7-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.1-flash-lite-preview",
    "gemini-3.1-pro-preview",
    "gemini-3.6-flash",
})

ANTIGRAVITY_MODELS: frozenset[str] = frozenset({
    "gemini-3.7-flash",
    "gemini-3.7-flash-tiered",
    "gemini-3.5-flash",
    "gemini-3.5-flash-extra-low",
    "gemini-3.5-flash-low",
    "gemini-3.1-pro-preview",
    "gemini-3.6-flash",
    "gemini-3.6-flash-high",
    "gemini-3.6-flash-medium",
    "gemini-3.6-flash-low",
    "gemini-3.6-flash-tiered",
    "gemini-3-flash-agent",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
})

ANTIGRAVITY_MODEL_ALIASES: dict[str, str] = {
    "gemini-3.7-flash": "gemini-3.7-flash-tiered",
}

ALL_MODELS: frozenset[str] = AISTUDIO_MODELS | ANTIGRAVITY_MODELS

_COMMON_PARAMETERS = ["tools", "response_format"]
_COMMON_CAPABILITIES: dict[str, Any] = {
    "streaming": True,
    "supported_protocols": ["responses", "chat_completions"],
    "supported_parameters": _COMMON_PARAMETERS,
}

# Direct Gemini facts come from Google's model documentation as captured in
# EMP's bundled official registry.  The Antigravity tiered facts are from the
# model catalog and live Codex acceptance observed through NA2H.
_KNOWN_MODELS: dict[str, dict[str, Any]] = {
    "gemini-3.7-flash": {
        "display_name": "Gemini 3.7 Flash",
        "context_window": 1_000_000,
        "output_limit": 65_536,
        "supports_reasoning": True,
        # Bare names may route to AI Studio or Antigravity. Advertise the
        # conservative overlap; the AGY tiered ID below is provider-specific.
        "reasoning_levels": ["low", "medium", "high"],
        "architecture": {
            "input_modalities": ["text", "image"],
            "output_modalities": ["text"],
        },
        "capability_source": "official",
    },
    "gemini-3.7-flash-tiered": {
        "display_name": "Gemini 3.7 Flash (Antigravity tiered)",
        "context_window": 1_048_576,
        "max_input_tokens": 1_048_576,
        "output_limit": 65_536,
        "supports_reasoning": True,
        "reasoning_levels": ["low", "medium", "high"],
        "architecture": {
            "input_modalities": ["text", "image"],
            "output_modalities": ["text"],
        },
        "capability_source": "observed",
    },
    "gemini-3.6-flash": {
        "display_name": "Gemini 3.6 Flash",
        "context_window": 1_000_000,
        "output_limit": 65_536,
        "supports_reasoning": True,
        "reasoning_levels": ["low", "medium", "high"],
        "architecture": {
            "input_modalities": ["text", "image"],
            "output_modalities": ["text"],
        },
        "capability_source": "official",
    },
    "gemini-2.5-flash": {
        "display_name": "Gemini 2.5 Flash",
        "context_window": 1_000_000,
        "output_limit": 65_536,
        "supports_reasoning": True,
        "architecture": {
            "input_modalities": ["text", "image"],
            "output_modalities": ["text"],
        },
        "capability_source": "official",
    },
    "gemini-2.5-pro": {
        "display_name": "Gemini 2.5 Pro",
        "context_window": 1_000_000,
        "output_limit": 65_536,
        "supports_reasoning": True,
        "architecture": {
            "input_modalities": ["text", "image"],
            "output_modalities": ["text"],
        },
        "capability_source": "official",
    },
}


def resolve_antigravity_model(model: str) -> str:
    """Resolve a product-facing Antigravity alias to the upstream model ID."""
    normalized = model.strip().lower()
    return ANTIGRAVITY_MODEL_ALIASES.get(normalized, normalized)


def model_discovery_entry(model_id: str) -> dict[str, Any]:
    """Return one OpenAI model entry with capability metadata when known."""
    entry: dict[str, Any] = {
        "id": model_id,
        "object": "model",
        "created": 0,
        "owned_by": "google",
        **deepcopy(_COMMON_CAPABILITIES),
    }
    known = deepcopy(_KNOWN_MODELS.get(model_id, {}))
    source = known.pop("capability_source", "unknown")
    if known.get("supports_reasoning"):
        entry["supported_parameters"] = ["reasoning", *_COMMON_PARAMETERS]
    entry.update(known)

    sourced_fields = (
        "context_window",
        "max_input_tokens",
        "output_limit",
        "supports_reasoning",
        "reasoning_levels",
    )
    entry["capability_sources"] = {
        field: {"source": source if field in entry else "unknown"}
        for field in sourced_fields
    }
    architecture = entry.get("architecture")
    entry["capability_sources"].update({
        "input_modalities": {
            "source": source
            if isinstance(architecture, dict) and architecture.get("input_modalities")
            else "unknown"
        },
        "output_modalities": {
            "source": source
            if isinstance(architecture, dict) and architecture.get("output_modalities")
            else "unknown"
        },
        "streaming": {"source": "observed"},
        "structured_tools": {"source": "observed"},
        "structured_output": {"source": "observed"},
        "supported_protocols": {"source": "observed"},
    })
    return entry


def list_model_discovery_entries() -> list[dict[str, Any]]:
    """Return the stable, sorted model discovery catalog."""
    return [model_discovery_entry(model_id) for model_id in sorted(ALL_MODELS)]
