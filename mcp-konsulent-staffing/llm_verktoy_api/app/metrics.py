from __future__ import annotations

from prometheus_client import Counter, Gauge

# ---- LLM / OpenRouter ----
llm_fallback_total = Counter(
    "llm_fallback_total",
    "Number of times deterministic fallback was used",
    ["provider", "reason"],
)
llm_budget_skip_total = Counter(
    "llm_budget_skip_total",
    "Number of times LLM call was skipped due to budget/cost pre-check",
    ["provider", "reason"],
)

openrouter_requests_total = Counter("openrouter_requests_total", "OpenRouter requests", ["model", "status"])
openrouter_cost_credits_total = Counter("openrouter_cost_credits_total", "Cost in credits (sum)")
openrouter_cost_last = Gauge("openrouter_cost_credits_last", "Cost in credits (last request)")
openrouter_daily_cost_credits = Gauge("openrouter_daily_cost_credits", "Daily cost in credits (rolling)")

# ---- Audit / Health / Rate limit ----
audit_events_total = Counter("audit_events_total", "Audit events recorded", ["action", "ok"])
rate_limit_hits_total = Counter("rate_limit_hits_total", "Rate limit (429) responses", ["path"])

dependency_up = Gauge("dependency_up", "Dependency health (1=up,0=down)", ["dependency"])
service_health_ok = Gauge("service_health_ok", "Service health (1=ok,0=degraded)")


# ---- Semantic cache / caching ----
semantic_cache_hit_total = Counter(
    "semantic_cache_hit_total",
    "Number of times semantic cache returned a cached summary",
    ["fingerprint"],
)
semantic_cache_store_total = Counter(
    "semantic_cache_store_total",
    "Number of times a new semantic cache entry was stored",
    ["fingerprint"],
)
konsulenter_cached_total = Counter(
    "konsulenter_cached_total",
    "Number of times consultants list was served from cache",
    ["layer"],
)


# Track semantic-cache usage beyond "returned cached summary".
# - semantic_context_requests_total increments when we attach semantic examples to the prompt.
# - semantic_context_examples_total increments by the number of examples attached (so the rate reflects intensity).
# - semantic_similarity_lookups_total increments whenever we run a similarity scan (cache-return or context).
semantic_similarity_lookups_total = Counter(
    "semantic_similarity_lookups_total",
    "Number of semantic similarity scans performed",
)
semantic_context_requests_total = Counter(
    "semantic_context_requests_total",
    "Number of requests where semantic examples were attached to the prompt",
)
semantic_context_examples_total = Counter(
    "semantic_context_examples_total",
    "Number of semantic examples attached to prompts (sum)",
)
# ---- OpenRouter key status (from /api/v1/key) ----
openrouter_key_limit = Gauge("openrouter_key_limit", "OpenRouter key spend limit (USD)")
openrouter_key_limit_remaining = Gauge("openrouter_key_limit_remaining", "OpenRouter key spend limit remaining (USD)")
openrouter_key_usage_total = Gauge("openrouter_key_usage_total", "OpenRouter key usage total (USD)")
openrouter_key_usage_daily = Gauge("openrouter_key_usage_daily", "OpenRouter key usage daily (USD)")
openrouter_key_usage_weekly = Gauge("openrouter_key_usage_weekly", "OpenRouter key usage weekly (USD)")
openrouter_key_usage_monthly = Gauge("openrouter_key_usage_monthly", "OpenRouter key usage monthly (USD)")
openrouter_key_is_free_tier = Gauge("openrouter_key_is_free_tier", "OpenRouter key is free tier (1/0)")

openrouter_key_monitor_last_success_unixtime = Gauge(
    "openrouter_key_monitor_last_success_unixtime",
    "Unix timestamp of last successful OpenRouter /key poll",
)
openrouter_key_monitor_failures_total = Counter(
    "openrouter_key_monitor_failures_total",
    "Number of failed OpenRouter /key polls",
)
openrouter_key_present = Gauge(
    "openrouter_key_present",
    "Whether OPENROUTER_API_KEY is configured (1/0)",
)


# ---------------------------------------------------------------------------
# IMPORTANT: Prometheus does *not* export Gauges until they have at least one
# sample value. If a Gauge is never `.set(...)` it simply won't appear under
# `/metrics`, and Grafana panels will show "No data".
#
# To make dashboards reliable, we initialize all OpenRouter key Gauges to 0 at
# import time. The background key-monitor task updates them periodically.
# ---------------------------------------------------------------------------
openrouter_key_limit.set(0.0)
openrouter_key_limit_remaining.set(0.0)
openrouter_key_usage_total.set(0.0)
openrouter_key_usage_daily.set(0.0)
openrouter_key_usage_weekly.set(0.0)
openrouter_key_usage_monthly.set(0.0)
openrouter_key_is_free_tier.set(0.0)
openrouter_key_monitor_last_success_unixtime.set(0.0)
openrouter_key_present.set(0.0)
