# MCP – Konsulent staffing (FastAPI + Docker Compose)

Dette repoet løser oppgaven med to mikrotjenester (server + klient) og en  dev-mode pakke rundt LLM-kallet (OpenRouter + observability + caching/failsafes).

---

**Dette er kommandoen som starter “hele opplevelsen” (Grafana/Prometheus + Redis + Nginx reverse proxy):**

```bash
docker compose --profile obs --profile redis --profile edge up -d --build
```

**Hovedgrensesnitt (Nginx reverse proxy):**
- http://localhost:8080/

Endepunkter via reverse proxy:
- http://localhost:8080/konsulenter
- http://localhost:8080/tilgjengelige-konsulenter/sammendrag?min_tilgjengelighet_prosent=50&p%C3%A5krevd_ferdighet=Python

Direkte (uten reverse proxy):
- `konsulent_api`: http://localhost:8001/konsulenter
- `llm_verktoy_api`: http://localhost:8002/tilgjengelige-konsulenter/sammendrag?min_tilgjengelighet_prosent=50&p%C3%A5krevd_ferdighet=Python

Observability:
- Grafana: http://localhost:3000  (default: `admin` / `admin` hvis ikke endret)
- Prometheus: http://localhost:9090

---

## 🧪 Kommandoene for å sammenligne modeller 

### 1) Prompt-matrise (flere modeller, to ferdigheter, to prompt-stiler)
**PowerShell (en-linje, robust):**
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\prompt_matrix.ps1 -Models "openrouter:deepseek/deepseek-v3.2","google/gemini-2.0-flash-001" -Skills "Python","Azure" -PromptStyles "strict","friendly" -Runs 2
```

### 2) Sammenlign modeller / velg “best”
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\compare_models.ps1
```

Dette leser `out/prompt_matrix_results.jsonl`, scorer svar (format/sikkerhet/fallback/latency/kost), og skriver:
- `out/model_comparison.json` (leaderboard + “best model”)

### 3) Enhetstester (repo-funksjoner)
```powershell
pytest -q
```

### 4) Trafikk-generator (for å se live-grafer i Grafana)
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\traffic_generator.ps1 -Requests 200 -DelayMs 150
```

---

## 📌 Oppgaven (kort)
- **konsulent_api**: `GET /konsulenter` → hardkodet JSON-liste med `id`, `navn`, `ferdigheter`, `belastning_prosent`.
- **llm_verktoy_api**: `GET /tilgjengelige-konsulenter/sammendrag` → henter konsulenter fra serveren, filtrerer, og returnerer:
  ```json
  {"sammendrag": "Fant X ...", "meta": {...}}
  ```

---

## 🧠 LLM-flyten (hvordan promptene blir laget)
1) `llm_verktoy_api` henter alle konsulenter fra `konsulent_api`
2) Filtrerer på:
   - `min_tilgjengelighet_prosent`
   - `påkrevd_ferdighet` (case-insensitive)
3) Tar en **top-N** (for å unngå lange prompts/svar)
4) Bygger prompt basert på `prompt_style` (f.eks. `strict` / `friendly`)
5) Kaller LLM-provider (OpenRouter eller local GGUF)
6) Validerer output → hvis output ikke matcher krav (eller LLM feiler), brukes deterministisk fallback
7) Returnerer JSON med `sammendrag` + `meta`

---

## 🔒 Kvalitet / sikkerhet / robusthet (det som faktisk finnes i repoet)
- **Rate limiting** (SlowAPI) på LLM-verktøy-endepunktet
- **PII-scrubbing** før logging (best-effort)
- **Audit log** (`/audit`) for å se hva som skjedde per request (inkl. fallback reason)
- **Metrics** (`/metrics`) + Grafana dashboards:
  - latency (p95), 5xx, budget skips, cache hits osv.
  - OpenRouter key usage / remaining (poller OpenRouter `/key` og eksponerer som Prometheus gauges)
- **Caching**
  - fetch-konsulenter caching (og valgfritt Redis)
  - semantic caching (hvis aktivert i config)
- **Failsafe**:
  - hvis LLM svarer dårlig/ugyldig eller feiler → deterministisk sammendrag i riktig format (og meta markerer fallback)

---

## 🔧 Konfig (nøkkelverdier)
Dette repoet bruker `.env` / miljøvariabler for toggles og nøkler.

Vanlige:
- `OPENROUTER_ENABLED=true/false`
- `OPENROUTER_API_KEY=...`
- `OPENROUTER_MODEL=...` (kan overstyres per request med `openrouter_model=...`)
- `LOCAL_GGUF_ENABLED=true/false`
- `REDIS_ENABLED=true/false`

---

## 🦙 Local GGUF (for testing uten OpenRouter)
Hvis du vil kjøre lokalt (llama.cpp server), legg modellen her:
- `models/model.gguf`

og start med profilene som inkluderer local GGUF (avhenger av compose i repoet):
```bash
docker compose --profile local-gguf up -d --build
```

---

## 📎 Nyttige endepunkt
- Health: `GET /health`
- Metrics: `GET /metrics`
- Audit: `GET /audit`

---

## 📂 Output fra scripts
- `out/prompt_matrix_results.jsonl` – alle requests (inputs + output + meta)
- `out/prompt_matrix_summary.json` – aggregert summary
- `out/model_comparison.json` – leaderboard + “best model”
