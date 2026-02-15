from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Tuple

import redis as redis_lib

from app.adapters.konsulent_api_adapter import KonsulentApiAdapter
from app.adapters.llm_adapter import LLMAdapter, LlamaCppServerAdapter, OpenRouterAdapter, NoopAdapter
from app.core.cache import MemoryCache
from app.core.audit import AuditLog
from app.core.resilience import CircuitBreaker
from app.core.settings import settings
from app.metrics import (
    audit_events_total,
    llm_budget_skip_total,
    llm_fallback_total,
    openrouter_cost_credits_total,
    openrouter_cost_last,
    openrouter_daily_cost_credits,
    openrouter_requests_total,
    semantic_cache_hit_total,
    semantic_cache_store_total,
    konsulenter_cached_total,
    semantic_similarity_lookups_total,
    semantic_context_requests_total,
    semantic_context_examples_total,
)
from app.core.models import Konsulent, Ok, Err
from app.semantic_cache import SemanticCache
from app.usage_store import UsageEvent, UsageStore
from app.validator import validate_schema_obj
from app.prompts import build_prompt, sammendrag_json_schema, looks_clean



logger = logging.getLogger(__name__)


class LLMService:
    def __init__(self):
        # Adapters / dependencies
        self.konsulent_adapter = KonsulentApiAdapter(settings.konsulent_api_url)
        self.cache = MemoryCache()

        self._redis = redis_lib.from_url(settings.redis_url, decode_responses=True) if settings.redis_enabled else None
        self.audit = AuditLog(redis=self._redis)
        # UsageStore mirrors to Redis automatically when redis_enabled=true
        self.usage = UsageStore()

        # Semantic similarity cache (optional)
        self.semantic_cache = SemanticCache(
            redis=self._redis if settings.redis_enabled and settings.semantic_cache_enabled else None,
            max_entries=settings.semantic_cache_max_entries,
        )

        # Circuit breakers (LLM providers)
        self.cb_openrouter = CircuitBreaker(
            name="openrouter",
            failure_threshold=settings.openrouter_cb_failure_threshold,
            recovery_timeout_seconds=settings.openrouter_cb_recovery_timeout_seconds,
        )
        self.cb_llama = CircuitBreaker(
            name="llama_cpp",
            failure_threshold=settings.llama_cb_failure_threshold,
            recovery_timeout_seconds=settings.llama_cb_recovery_timeout_seconds,
        )

    async def fetch_konsulenter(self) -> Tuple[List[Konsulent], bool]:
        """Fetches consultants from konsulent_api with a tiny shared cache (Redis optional)."""
        cache_key = "konsulenter:v1"

        # Redis shared cache first
        if self._redis:
            cached_json = self._redis.get(cache_key)
            if cached_json:
                try:
                    data = json.loads(cached_json)
                    kons = [
                        Konsulent(
                            id=int(k["id"]),
                            navn=k["navn"],
                            ferdigheter=tuple([str(s).lower() for s in (k.get("ferdigheter") or [])]),
                            belastning_prosent=int(k["belastning_prosent"]),
                        )
                        for k in data
                    ]
                    konsulenter_cached_total.labels("redis").inc()
                    return kons, True
                except Exception:
                    pass

        # In-memory cache
        cached = self.cache.get(cache_key)
        if cached is not None:
            konsulenter_cached_total.labels("memory").inc()
            return cached, True

        # Fetch from konsulent_api (adapter includes retry + circuit breaker)
        res = await self.konsulent_adapter.get_all()
        if isinstance(res, Ok):
            kons = res.value
        else:
            # In this demo, if konsulent_api is down we return an empty list.
            # The calling endpoint will still respond deterministically.
            self.audit.add("n/a", "konsulent_api_error", {"error": res.error.message, "code": str(res.error.code)}, ok=False, error=res.error.message)
            audit_events_total.labels("konsulent_api_error", "false").inc()
            kons = []

        # Store
        self.cache.set(cache_key, kons, ttl_seconds=settings.cache_ttl_seconds)
        if self._redis:
            try:
                payload = [
                    {"id": k.id, "navn": k.navn, "ferdigheter": list(k.ferdigheter), "belastning_prosent": k.belastning_prosent}
                    for k in kons
                ]
                self._redis.setex(cache_key, settings.cache_ttl_seconds, json.dumps(payload, ensure_ascii=False))
            except Exception:
                pass

        return kons, False

    def _choose_llm_adapter(self, model_override: str | None = None) -> LLMAdapter:
        """Priority: OpenRouter (if enabled+key) -> local llama.cpp server (if enabled)."""
        if settings.openrouter_enabled and settings.openrouter_api_key:
            return OpenRouterAdapter(
                api_key=settings.openrouter_api_key,
                model=(model_override or settings.openrouter_model),
                base_url=settings.openrouter_base_url,
                max_tokens=settings.openrouter_max_tokens,
                temperature=settings.openrouter_temperature,
                structured_outputs=settings.openrouter_structured_outputs,
                app_name=settings.openrouter_app_name,
                referer=settings.openrouter_app_referer,
                response_healing=settings.openrouter_response_healing,
            )

        if settings.local_gguf_enabled:
            return LlamaCppServerAdapter(
                base_url=settings.llama_cpp_base_url,
                timeout=settings.llama_cpp_timeout_seconds,
                max_tokens=settings.openrouter_max_tokens,
                temperature=settings.openrouter_temperature,
            )

        # If we get here there is no configured LLM provider; we fail fast with a noop adapter.
        if settings.openrouter_enabled and not settings.openrouter_api_key:
            logger.warning("OpenRouter enabled but OPENROUTER_API_KEY is empty; using deterministic fallback.")
        return NoopAdapter()

    def _estimate_max_cost_credits(self, prompt: str) -> float:
        """Best-effort *pre-check* cost estimate for OpenRouter calls.

        Strategy:
        - If OPENROUTER_COST_CREDITS_PER_1K_PROMPT and _COMPLETION are set (>=0), use them.
        - Otherwise return 0 (unknown/assume-free) and rely on post-usage accounting + daily budget.
        """
        if settings.openrouter_cost_credits_per_1k_prompt >= 0 and settings.openrouter_cost_credits_per_1k_completion >= 0:
            prompt_tokens_est = max(1, int(len(prompt) / max(1, settings.openrouter_chars_per_token)))
            prompt_cost = (prompt_tokens_est / 1000.0) * settings.openrouter_cost_credits_per_1k_prompt
            completion_cost = (settings.openrouter_max_tokens / 1000.0) * settings.openrouter_cost_credits_per_1k_completion
            return float(prompt_cost + completion_cost)
        return 0.0

    async def generate_sammendrag(
        self,
        *,
        request_id: str,
        min_tilgjengelighet: int,
        pakrevd_ferdighet: str,
        konsulenter: List[Konsulent],
        konsulenter_cached: bool,
        model_override: str | None = None,
        prompt_style: str = "strict",
    ) -> Tuple[str, bool, str, Dict[str, Any]]:
        t0 = time.time()

        # Filter
        matches = [
            k
            for k in konsulenter
            if (100 - k.belastning_prosent) >= min_tilgjengelighet
            and any(pakrevd_ferdighet.lower() == f.lower() for f in k.ferdigheter)
        ]
        matches.sort(key=lambda k: (100 - k.belastning_prosent), reverse=True)
        total_matchende = len(matches)

        # Top-N policy to keep answers short + cheap
        truncated = False
        if total_matchende > settings.max_matching_konsulenter:
            matches = matches[: settings.max_matching_konsulenter]
            truncated = True

        # Prepare prompt data
        prompt_matches = [
            {
                "navn": k.navn,
                "tilgjengelighet_prosent": (100 - k.belastning_prosent),
                "ferdigheter": k.ferdigheter,
            }
            for k in matches
        ]

        # Used to validate LLM outputs (and semantic cache hits) against the current allowed names/prosents.
        allowed_pairs = [(d["navn"], d["tilgjengelighet_prosent"]) for d in prompt_matches]

        # Semantic cache fingerprint is stable for this "query category".
        fingerprint = f"skill:{pakrevd_ferdighet.lower()}|min:{min_tilgjengelighet}|style:{(prompt_style or 'strict').lower()}"
        query_text = f"{pakrevd_ferdighet} {min_tilgjengelighet}% tilgjengelighet"

        # If semantic cache enabled, optionally return cached answer early.
        if self.semantic_cache.enabled() and settings.semantic_cache_return_cached:
            cached_hit = self.semantic_cache.maybe_get_cached(
                fingerprint=fingerprint,
                query=query_text,
                threshold=settings.semantic_cache_similarity_threshold,
                limit_scan=settings.semantic_cache_limit_scan,
            )
            if cached_hit:
                cached_obj, sim, cached_meta = cached_hit
                ok_cached, _why = validate_schema_obj(cached_obj, allowed_pairs)
                if ok_cached and looks_clean(str(cached_obj.get("sammendrag", ""))):
                    self.audit.add(request_id, "semantic_cache_hit", {"sim": sim, "provider": "cache"}, ok=True)
                    audit_events_total.labels("semantic_cache_hit", "true").inc()
                    semantic_cache_hit_total.labels(fingerprint).inc()
                    return (
                        str(cached_obj.get("sammendrag", "")).strip(),
                        False,
                        "ok_semantic_cached",
                        self._meta(
                            provider="semantic_cache",
                            cached=konsulenter_cached,
                            t0=t0,
                            total_matchende=total_matchende,
                            antall_listet=len(matches),
                            truncated=truncated,
                            cost=0.0,
                            usage={"semantic_similarity": sim, **(cached_meta or {})},
                        ),
                    )

        # If semantic cache enabled, use top-K examples to guide style.
        examples = []
        if self.semantic_cache.enabled() and settings.semantic_cache_use_as_context:
            examples = self.semantic_cache.context_examples(
                fingerprint=fingerprint,
                query=query_text,
                k=settings.semantic_cache_top_k,
                limit_scan=settings.semantic_cache_limit_scan,
            )

        # If we attach examples, track it so Grafana reflects real semantic usage (not only cache hits).
        if examples:
            semantic_context_requests_total.inc()
            semantic_context_examples_total.inc(len(examples))

        prompt = build_prompt(
            min_tilgjengelighet=min_tilgjengelighet,
            pakrevd_ferdighet=pakrevd_ferdighet,
            konsulenter=prompt_matches,
            total_matchende=total_matchende,
            truncated=truncated,
            prompt_style=prompt_style,
            examples=examples,
        )

        adapter = self._choose_llm_adapter(model_override)
        provider = adapter.provider_name
        schema = sammendrag_json_schema()

        # ---- Budget guards ----
        daily_cost = self.usage.daily_cost()
        openrouter_daily_cost_credits.set(daily_cost)

        if settings.openrouter_enabled and not settings.openrouter_api_key:
            self.audit.add(request_id, "openrouter_missing_key", {}, ok=False, error="OPENROUTER_API_KEY not set")
            audit_events_total.labels("openrouter_missing_key", "false").inc()

        if settings.openrouter_enabled and daily_cost >= settings.cost_budget_credits_daily:
            reason = "cost_budget_exceeded"
            llm_budget_skip_total.labels(provider, reason).inc()
            self.audit.add(request_id, "llm_skipped_budget", {"daily_cost": daily_cost}, ok=False, error=reason)
            audit_events_total.labels("llm_skipped_budget", "false").inc()
            return (
                self._deterministic_summary(min_tilgjengelighet, pakrevd_ferdighet, matches, total_matchende, truncated),
                True,
                reason,
                self._meta(provider, konsulenter_cached, t0, total_matchende, len(matches), truncated, cost=0.0),
            )

        if settings.openrouter_enabled and provider.startswith("openrouter:"):
            est_cost = self._estimate_max_cost_credits(prompt)
            if est_cost and est_cost > settings.max_cost_credits_per_request:
                reason = "cost_estimate_over_limit"
                llm_budget_skip_total.labels(provider, reason).inc()
                self.audit.add(request_id, "llm_skipped_cost_estimate", {"estimated_cost": est_cost}, ok=False, error=reason)
                audit_events_total.labels("llm_skipped_cost_estimate", "false").inc()
                return (
                    self._deterministic_summary(min_tilgjengelighet, pakrevd_ferdighet, matches, total_matchende, truncated),
                    True,
                    reason,
                    self._meta(provider, konsulenter_cached, t0, total_matchende, len(matches), truncated, cost=0.0),
                )

        # ---- Optional exact-match cache (Redis) ----
        if self._redis and settings.llm_cache_enabled and provider.startswith("openrouter:"):
            try:
                import hashlib

                cache_key = "llmcache:v1:" + hashlib.sha256((provider + "|" + prompt).encode("utf-8")).hexdigest()
                cached = self._redis.get(cache_key)
                if cached:
                    obj = json.loads(cached)
                    ok, _ = validate_schema_obj(obj, allowed_pairs)
                    if ok and looks_clean(obj.get("sammendrag", "")):
                        self.audit.add(request_id, "llm_cache_hit", {"provider": provider}, ok=True)
                        audit_events_total.labels("llm_cache_hit", "true").inc()
                        return (
                            obj["sammendrag"].strip(),
                            False,
                            "ok_cached",
                            self._meta(provider, konsulenter_cached, t0, total_matchende, len(matches), truncated, cost=0.0, usage={"cache_hit": True}),
                        )
            except Exception:
                pass

        # ---- Call LLM ----
        cost = 0.0
        usage_meta: Dict[str, Any] = {}

        # Circuit breaker guard (prevents hammering a failing provider)
        cb = self.cb_openrouter if provider.startswith("openrouter:") else self.cb_llama
        if settings.llm_circuit_breaker_enabled and not cb.allow_request():
            fallback_reason = f"circuit_open:{cb.name}"
            llm_fallback_total.labels(provider, fallback_reason).inc()
            self.audit.add(request_id, "llm_circuit_open", {"provider": provider, "cb": cb.get_stats()}, ok=False, error=fallback_reason)
            audit_events_total.labels("llm_circuit_open", "false").inc()
            sammendrag = self._deterministic_summary(min_tilgjengelighet, pakrevd_ferdighet, matches, total_matchende, truncated)
            return (
                sammendrag,
                True,
                fallback_reason,
                self._meta(provider, konsulenter_cached, t0, total_matchende, len(matches), truncated, cost=0.0, usage={"cb": cb.get_stats()}),
            )
        try:
            result = await adapter.generate_json(prompt=prompt, schema=schema)
        except Exception as e:
            from app.core.models import ServiceError, ErrorCode

            result = Err(ServiceError(code=ErrorCode.LLM_API_ERROR, message=f"{type(e).__name__}: {e}", details={"status_code": 502}))

        # Update circuit breaker after call
        try:
            if isinstance(result, Ok):
                await cb.record_success()
            else:
                await cb.record_failure()
        except Exception:
            pass

        if isinstance(result, Ok):
            obj, usage_meta = result.value
            ok, why = validate_schema_obj(obj, allowed_pairs)

            # If validation failed and response-healing is enabled, try once more.
            if not ok and settings.openrouter_enabled and settings.openrouter_response_healing:
                obj2, usage2, heal_ok, _ = await self._heal_response(adapter, schema, obj, why, prompt, allowed_pairs)
                usage_meta = self._merge_usage(usage_meta, usage2)
                if heal_ok:
                    obj = obj2
                    ok = True

            if ok:
                sammendrag = str(obj.get("sammendrag", "")).strip()

                # Extra safety: forbid profanity / negativity
                if not looks_clean(sammendrag):
                    ok = False
                    why = "negative_or_profanity"

            if ok:
                # Cost accounting (best-effort)
                cost = float(usage_meta.get("cost", 0.0) or 0.0)
                self._record_usage(request_id, adapter, usage_meta, cost)

                # Post-check guard (signals over-limit)
                if settings.openrouter_enabled and cost and cost > settings.max_cost_credits_per_request:
                    self.audit.add(request_id, "cost_over_limit", {"cost": cost, "limit": settings.max_cost_credits_per_request}, ok=False, error="cost_over_limit")
                    audit_events_total.labels("cost_over_limit", "false").inc()

                # Cache successful OpenRouter result
                if self._redis and settings.llm_cache_enabled and provider.startswith("openrouter:"):
                    try:
                        import hashlib

                        cache_key = "llmcache:v1:" + hashlib.sha256((provider + "|" + prompt).encode("utf-8")).hexdigest()
                        self._redis.setex(cache_key, settings.llm_cache_ttl_seconds, json.dumps(obj, ensure_ascii=False))
                    except Exception:
                        pass

                # Semantic cache store (few-shot guidance + long-term semantic caching)
                if self.semantic_cache.enabled() and settings.semantic_cache_enabled:
                    try:
                        self.semantic_cache.put(
                            fingerprint=fingerprint,
                            query=query_text,
                            obj=obj,
                            meta={"provider": provider, "prompt_style": prompt_style, "truncated": truncated},
                        )
                        audit_events_total.labels("semantic_cache_store", "true").inc()
                        semantic_cache_store_total.labels(fingerprint).inc()
                    except Exception:
                        pass

                return (
                    sammendrag,
                    False,
                    "ok",
                    self._meta(provider, konsulenter_cached, t0, total_matchende, len(matches), truncated, cost=cost, usage=usage_meta),
                )

            # Validation / policy failure -> fallback
            fallback_reason = f"llm_validation_failed:{why}"
        else:
            fallback_reason = f"llm_error:{result.error.message}"

        # Deterministic fallback
        sammendrag = self._deterministic_summary(min_tilgjengelighet, pakrevd_ferdighet, matches, total_matchende, truncated)
        llm_fallback_total.labels(provider, fallback_reason).inc()
        self.audit.add(request_id, "llm_fallback", {"provider": provider, "reason": fallback_reason}, ok=False, error=fallback_reason)
        audit_events_total.labels("llm_fallback", "false").inc()
        return (
            sammendrag,
            True,
            fallback_reason,
            self._meta(provider, konsulenter_cached, t0, total_matchende, len(matches), truncated, cost=cost, usage=usage_meta),
        )

    async def _heal_response(
        self,
        adapter: LLMAdapter,
        schema: Dict[str, Any],
        bad_obj: Dict[str, Any],
        why: str,
        original_prompt: str,
        allowed_pairs: List[Tuple[str, int]],
    ) -> Tuple[Dict[str, Any], Dict[str, Any], bool, str]:
        fix_prompt = f"""Du returnerte et ugyldig svar.

FEIL: {why}

OPPGAVE:
- Returner KUN gyldig JSON som matcher schemaet.
- Ikke legg til nye felter.

SCHEMA:
{json.dumps(schema, ensure_ascii=False)}

ORIGINAL PROMPT:
{original_prompt}

DÅRLIG SVAR (for referanse):
{json.dumps(bad_obj, ensure_ascii=False)}
"""
        r = await adapter.generate_json(prompt=fix_prompt, schema=schema)
        if isinstance(r, Ok):
            obj, usage = r.value
            ok, _ = validate_schema_obj(obj, allowed_pairs)
            if ok and looks_clean(str(obj.get("sammendrag", ""))):
                return obj, usage, True, "ok"
            return obj, usage, False, "heal_validation_failed"
        return {}, {}, False, "heal_call_failed"

    def _merge_usage(self, a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(a or {})
        for k in ("prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens"):
            out[k] = int(out.get(k, 0) or 0) + int(b.get(k, 0) or 0)
        out["cost"] = float(out.get("cost", 0.0) or 0.0) + float(b.get("cost", 0.0) or 0.0)
        out["cache_hit"] = bool(out.get("cache_hit", False)) or bool(b.get("cache_hit", False))
        return out

    def _record_usage(self, request_id: str, adapter: LLMAdapter, usage_meta: Dict[str, Any], cost: float) -> None:
        try:
            openrouter_cost_last.set(cost or 0.0)
            openrouter_cost_credits_total.inc(cost or 0.0)
            openrouter_daily_cost_credits.set(self.usage.daily_cost())
            openrouter_requests_total.labels(adapter.provider_name, "ok").inc()
        except Exception:
            pass

        evt = UsageEvent(
            ts=time.time(),
            request_id=request_id,
            provider=adapter.provider_name,
            model=adapter.provider_name,
            prompt_tokens=int(usage_meta.get("prompt_tokens", 0) or 0),
            completion_tokens=int(usage_meta.get("completion_tokens", 0) or 0),
            total_tokens=int(usage_meta.get("total_tokens", 0) or 0),
            cost=float(cost or 0.0),
            cached_tokens=int(usage_meta.get("cached_tokens", 0) or 0),
            cache_hit=bool(usage_meta.get("cache_hit", False)),
        )
        self.usage.add(evt)

    def _meta(
        self,
        provider: str,
        cached: bool,
        t0: float,
        total_matchende: int,
        antall_listet: int,
        truncated: bool,
        cost: float,
        usage: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        return {
            "antall_matchende": total_matchende,
            "antall_listet": antall_listet,
            "truncated": truncated,
            "provider": provider,
            "konsulenter_cached": cached,
            "fallback_used": False,  # set by caller
            "fallback_reason": "ok",
            "prosessering_ms": round((time.time() - t0) * 1000.0, 2),
            "cost_credits": round(float(cost or 0.0), 6),
            "usage": usage or {},
        }

    def _deterministic_summary(
        self,
        min_tilgjengelighet: int,
        pakrevd_ferdighet: str,
        matches: List[Konsulent],
        total_matchende: int,
        truncated: bool,
    ) -> str:
        if not matches:
            return f"Fant 0 konsulenter med minst {min_tilgjengelighet}% tilgjengelighet og ferdigheten '{pakrevd_ferdighet}'."
        parts = [f"Fant {total_matchende} konsulenter med minst {min_tilgjengelighet}% tilgjengelighet og ferdigheten '{pakrevd_ferdighet}'."]
        if truncated and total_matchende > len(matches):
            parts.append(f"Viser topp-{len(matches)} (sortert på tilgjengelighet).")
        for k in matches:
            parts.append(f"{k.navn} har {k.tilgjengelighet_prosent}% tilgjengelighet.")
        return " ".join(parts)
