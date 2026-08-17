"""Tests for pricing computation."""

from hakimi_proxy.metering.models import TokenBreakdown
from hakimi_proxy.metering.pricing import BUILTIN_PRICING, compute_cost, compute_cost_for_model, get_pricing


def test_gemini_37_flash_pricing():
    """Verify 3.7 Flash pricing matches official: $0.75/1M input, $3.75/1M output."""
    p = get_pricing("gemini-3.7-flash")
    assert p is not None
    assert abs(p.input_cost_per_token - 0.75 / 1_000_000) < 1e-15
    assert abs(p.output_cost_per_token - 3.75 / 1_000_000) < 1e-15


def test_compute_cost_basic():
    """1000 input + 500 output tokens for gemini-3.7-flash."""
    p = get_pricing("gemini-3.7-flash")
    usage = TokenBreakdown(input=1000, output=500)
    cost = compute_cost(p, usage)
    expected = (1000 * 0.75 + 500 * 3.75) / 1_000_000
    assert abs(cost - expected) < 1e-10


def test_compute_cost_with_cache_and_reasoning():
    """Cache_read and reasoning are priced correctly."""
    p = get_pricing("gemini-3.7-flash")
    usage = TokenBreakdown(input=1000, output=500, cache_read=200, cache_write=100, reasoning=300)
    cost = compute_cost(p, usage)
    # cache_read price is 0 in built-in (no cache pricing configured)
    # reasoning defaults to output price
    expected = (
        1000 * 0.75 / 1e6
        + 500 * 3.75 / 1e6
        + 200 * 0.0  # cache_read
        + 100 * 0.0  # cache_write
        + 300 * 3.75 / 1e6  # reasoning defaults to output price
    )
    assert abs(cost - expected) < 1e-10


def test_compute_cost_unknown_model():
    """Unknown model returns 0 cost."""
    cost = compute_cost_for_model("nonexistent-model", TokenBreakdown(input=1000, output=500))
    assert cost == 0.0


def test_get_pricing_strips_prefix():
    """Pricing lookup strips provider prefixes like 'google/'."""
    p = get_pricing("google/gemini-3.7-flash")
    assert p is not None
    assert abs(p.input_cost_per_token - 0.75 / 1_000_000) < 1e-15


def test_builtin_pricing_covers_key_models():
    """Ensure key models are in the built-in pricing table."""
    expected = {"gemini-3.7-flash", "gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.1-pro-preview"}
    assert expected.issubset(BUILTIN_PRICING.keys())


def test_token_breakdown_total():
    """TokenBreakdown.total sums all dimensions."""
    tb = TokenBreakdown(input=10, output=20, cache_read=5, cache_write=3, reasoning=2)
    assert tb.total == 40


def test_usage_record_from_openai():
    """UsageRecord.from_openai_usage correctly splits prompt tokens."""
    from hakimi_proxy.metering.models import UsageRecord

    usage = {
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_tokens": 150,
        "prompt_tokens_details": {"cached_tokens": 30},
        "completion_tokens_details": {"reasoning_tokens": 10},
    }
    rec = UsageRecord.from_openai_usage(
        credential_id="test", model="gemini-3.7-flash", upstream="aistudio", usage=usage
    )
    assert rec.tokens.input == 70  # 100 - 30 cached
    assert rec.tokens.output == 50
    assert rec.tokens.cache_read == 30
    assert rec.tokens.reasoning == 10


def test_usage_record_from_gemini():
    """UsageRecord.from_gemini_usage correctly maps Gemini usageMetadata."""
    from hakimi_proxy.metering.models import UsageRecord

    meta = {
        "promptTokenCount": 100,
        "candidatesTokenCount": 50,
        "totalTokenCount": 150,
        "thoughtsTokenCount": 10,
        "cachedContentTokenCount": 30,
    }
    rec = UsageRecord.from_gemini_usage(
        credential_id="test", model="gemini-3.7-flash", upstream="antigravity", usage_metadata=meta
    )
    assert rec.tokens.input == 70  # 100 - 30 cached
    assert rec.tokens.output == 50
    assert rec.tokens.cache_read == 30
    assert rec.tokens.reasoning == 10
