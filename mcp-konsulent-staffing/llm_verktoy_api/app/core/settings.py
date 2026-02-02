from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Services
    konsulent_api_url: str = "http://konsulent_api:8000"

    # OpenRouter (default ON)
    openrouter_enabled: bool = True
    openrouter_api_key: str = ""
    openrouter_model: str = "meta-llama/llama-3.2-3b-instruct:free"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_structured_outputs: bool = True
    openrouter_response_healing: bool = True
    openrouter_max_tokens: int = 220
    openrouter_temperature: float = 0.4

    

    # OpenRouter key monitor (poll /api/v1/key and export to Prometheus)
    openrouter_key_monitor_enabled: bool = True
    openrouter_key_poll_seconds: int = 60

    # Optional OpenRouter attribution headers
    openrouter_app_name: str = "mcp-konsulent-staffing"
    openrouter_app_referer: str = "http://localhost"
    # Cost controls
    max_cost_credits_per_request: float = 0.02
    cost_budget_credits_daily: float = 2.0

    # Optional cost estimation (pre-check). If pricing is unknown, we fall back to heuristic chars/token.
    openrouter_pricing_auto: bool = True
    openrouter_cost_credits_per_1k_prompt: float = -1.0   # -1 => auto (if possible)
    openrouter_cost_credits_per_1k_completion: float = -1.0
    openrouter_chars_per_token: int = 4

    # Local GGUF via llama.cpp server
    local_gguf_enabled: bool = False
    llama_cpp_base_url: str = "http://llama_cpp:8080/v1"
    llama_cpp_timeout_seconds: int = 120
    local_model_path: str = "/models/model.gguf"

    # Redis optional
    redis_enabled: bool = False
    llm_cache_enabled: bool = False
    llm_cache_ttl_seconds: int = 300
    redis_url: str = "redis://redis:6379/0"
    cache_ttl_seconds: int = 30

    # Semantic similarity / semantic caching (optional, requires Redis enabled)
    semantic_cache_enabled: bool = False
    semantic_cache_return_cached: bool = True
    semantic_cache_use_as_context: bool = True
    semantic_cache_similarity_threshold: float = 0.88
    semantic_cache_top_k: int = 3
    semantic_cache_limit_scan: int = 200
    semantic_cache_max_entries: int = 500

    # Circuit breaker (LLM providers)
    llm_circuit_breaker_enabled: bool = True
    openrouter_cb_failure_threshold: int = 5
    openrouter_cb_recovery_timeout_seconds: int = 60
    llama_cb_failure_threshold: int = 5
    llama_cb_recovery_timeout_seconds: int = 30
    redis_circuit_breaker_enabled: bool = False

    # Rate limit
    rate_limit_enabled: bool = True
    rate_limit_default: str = "60/minute"
    rate_limit_storage_uri: str = "memory://"

    # Behaviour
    max_matching_konsulenter: int = 12
    log_response_bodies: bool = False
    metrics_enabled: bool = True
    log_level: str = "INFO"


settings = Settings()
