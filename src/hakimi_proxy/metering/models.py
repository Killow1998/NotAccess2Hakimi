"""Token usage data structures, modeled after tokscale's TokenBreakdown."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TokenBreakdown:
    """Five-dimensional token breakdown matching tokscale's model."""

    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    reasoning: int = 0

    @property
    def total(self) -> int:
        return self.input + self.output + self.cache_read + self.cache_write + self.reasoning

    def to_dict(self) -> dict:
        return {
            "input": self.input,
            "output": self.output,
            "cache_read": self.cache_read,
            "cache_write": self.cache_write,
            "reasoning": self.reasoning,
        }


@dataclass
class UsageRecord:
    """A single usage record for metering and cost tracking."""

    credential_id: str
    model: str
    upstream: str  # "aistudio" or "antigravity"
    tokens: TokenBreakdown
    cost_usd: float
    request_count: int = 1
    date: str = ""  # YYYY-MM-DD, filled by store

    @classmethod
    def from_openai_usage(
        cls,
        *,
        credential_id: str,
        model: str,
        upstream: str,
        usage: dict,
    ) -> "UsageRecord":
        """Build a UsageRecord from an OpenAI-format usage dict."""
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        # OpenAI usage may carry cache/reasoning details in prompt_tokens_details / completion_tokens_details
        prompt_details = usage.get("prompt_tokens_details") or {}
        completion_details = usage.get("completion_tokens_details") or {}

        cache_read = prompt_details.get("cached_tokens", 0)
        reasoning = completion_details.get("reasoning_tokens", 0)
        # cache_write is not standard in OpenAI; leave 0 unless explicitly present
        cache_write = usage.get("cache_write_tokens", 0)

        # Non-cached input = prompt_tokens - cache_read
        input_tokens = max(prompt_tokens - cache_read, 0)

        return cls(
            credential_id=credential_id,
            model=model,
            upstream=upstream,
            tokens=TokenBreakdown(
                input=input_tokens,
                output=completion_tokens,
                cache_read=cache_read,
                cache_write=cache_write,
                reasoning=reasoning,
            ),
            cost_usd=0.0,  # filled by caller via compute_cost
        )

    @classmethod
    def from_gemini_usage(
        cls,
        *,
        credential_id: str,
        model: str,
        upstream: str,
        usage_metadata: dict,
    ) -> "UsageRecord":
        """Build a UsageRecord from a Gemini generateContent usageMetadata dict."""
        prompt_tokens = usage_metadata.get("promptTokenCount", 0)
        output_tokens = usage_metadata.get("candidatesTokenCount", 0)
        total_tokens = usage_metadata.get("totalTokenCount", prompt_tokens + output_tokens)

        # Gemini may report thoughtsTokenCount for reasoning
        reasoning = usage_metadata.get("thoughtsTokenCount", 0)
        cached = usage_metadata.get("cachedContentTokenCount", 0)

        input_tokens = max(prompt_tokens - cached, 0)

        return cls(
            credential_id=credential_id,
            model=model,
            upstream=upstream,
            tokens=TokenBreakdown(
                input=input_tokens,
                output=output_tokens,
                cache_read=cached,
                reasoning=reasoning,
            ),
            cost_usd=0.0,
        )
