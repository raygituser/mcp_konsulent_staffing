<#############################################
prompt_matrix.ps1

Common usage (single-line is easiest)
-----------------------------------
Multi-model run (OpenRouter) - preferred single-line syntax:
  powershell -ExecutionPolicy Bypass -File .\scripts\prompt_matrix.ps1 -Models "openrouter:deepseek/deepseek-v3.2","google/gemini-2.0-flash-001" -Skills "Python","Azure" -PromptStyles "strict","friendly" -Runs 2

Tip: If you paste parameters onto new lines without line-continuation, PowerShell will treat them as separate commands (e.g. "-Models").


Goal
----
Run a small, repeatable test matrix against llm_verktoy_api and persist *everything*:
- the exact request URL (inputs)
- the generated summary text (output)
- meta (provider, fallback, latency, cost)

This is designed for your interview/demo so you can:
- compare prompt styles
- compare skills
- compare providers (OpenRouter vs local GGUF)

Output
------
Writes two files under .\out by default:
- prompt_matrix_results.jsonl  (one JSON object per request)
- prompt_matrix_summary.json   (aggregated stats)

Windows execution policy
------------------------
If PowerShell blocks the script, run:
  powershell -ExecutionPolicy Bypass -File .\scripts\prompt_matrix.ps1

Common usage (single-line is easiest)
-----------------------------------
Multi-model run (OpenRouter) - preferred single-line syntax:
  powershell -ExecutionPolicy Bypass -File .\scripts\prompt_matrix.ps1 -Models "openrouter:deepseek/deepseek-v3.2","google/gemini-2.0-flash-001" -Skills "Python","Azure" -PromptStyles "strict","friendly" -Runs 2

Tip: If you paste parameters onto new lines without line-continuation, PowerShell will treat them as separate commands (e.g. "-Models").

#############################################>

param(
  # Base URL for llm_verktoy_api (default: env:BASE_URL or http://localhost:8002)
  [string]$BaseUrl,

  # Skills to test. Example:
  #   -Skills @("Python","Azure")
  [string[]]$Skills = @("Python", "Azure"),

  # Prompt styles supported by the API. Keep to styles your service understands.
  # Example:
  #   -PromptStyles @("strict","friendly")
  [string[]]$PromptStyles = @("strict", "friendly"),

  # Models to test. Works with ONE model or MANY models.
  # - In OpenRouter mode, values are sent as openrouter_model=...
  # - In local GGUF mode, the server typically ignores this param.
  #
  # IMPORTANT:
  # '(default)' means: do NOT send an override in the query string. Let server pick.
  #
  # Examples:
  #   -Models @("openrouter:mistralai/mistral-small-3.1-24b-instruct:free")
  #   -Models @("(default)")
  [string[]]$Models = @('(default)'),

  # Minimum availability percent
  [int]$MinAvail = 50,

  # Runs per combo (skill x style x model)
  [int]$Runs = 1,

  # Sleep between calls (ms). Increase for local GGUF if you see 503/timeout.
  [int]$DelayMs = 300,

  # Output directory (default: <repo-root>\out)
  [string]$OutDir,

  # Optional: override output file path (JSONL). If set, OutDir is ignored.
  [string]$OutFile
)

# Fail fast on errors (param-block must be first executable element in a .ps1)
$ErrorActionPreference = "Stop"

# Resolve base URL
$base = $BaseUrl
if ([string]::IsNullOrWhiteSpace($base)) { $base = $env:BASE_URL }
if ([string]::IsNullOrWhiteSpace($base)) { $base = "http://localhost:8002" }

# Resolve repo root + output paths
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")

if ([string]::IsNullOrWhiteSpace($OutDir)) {
  $OutDir = Join-Path $repoRoot "out"
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

if ([string]::IsNullOrWhiteSpace($OutFile)) {
  $resultsPath = Join-Path $OutDir "prompt_matrix_results.jsonl"
} else {
  $resultsPath = $OutFile
  $parent = Split-Path -Parent $resultsPath
  if (-not [string]::IsNullOrWhiteSpace($parent)) {
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
  }
}

$summaryPath = Join-Path $OutDir "prompt_matrix_summary.json"

# Clean old outputs so it's obvious what's new
if (Test-Path $resultsPath) { Remove-Item $resultsPath -Force }
if (Test-Path $summaryPath) { Remove-Item $summaryPath -Force }

# Model defaults:
# - If user explicitly passed -Models, keep it.
# - If Models is empty, try env OPENROUTER_MODEL / OPENROUTER_MODEL_2.
# - Otherwise keep '(default)' (do NOT force local_gguf here).
if (-not $Models -or $Models.Count -eq 0) {
  $tmp = @()
  if (-not [string]::IsNullOrWhiteSpace($env:OPENROUTER_MODEL)) { $tmp += $env:OPENROUTER_MODEL }
  if (-not [string]::IsNullOrWhiteSpace($env:OPENROUTER_MODEL_2)) { $tmp += $env:OPENROUTER_MODEL_2 }
  if ($tmp.Count -gt 0) {
    $Models = $tmp
  } else {
    $Models = @('(default)')
  }
}

function Get-FirstExistingPropName([object]$obj, [string[]]$candidates) {
  if ($null -eq $obj) { return $null }

  # For PSCustomObject:
  $names = @()
  try { $names = $obj.PSObject.Properties.Name } catch { $names = @() }

  # For hashtable-like:
  $keys = @()
  try {
    if ($obj -is [System.Collections.IDictionary]) { $keys = @($obj.Keys) }
  } catch { $keys = @() }

  foreach ($c in $candidates) {
    if ($names -contains $c) { return $c }
    if ($keys -contains $c) { return $c }
  }
  return $null
}

function Invoke-Once([string]$Skill, [string]$Style, [string]$Model) {
  # Build query string
  $skillEncoded = [System.Uri]::EscapeDataString($Skill)
  $styleEncoded = [System.Uri]::EscapeDataString($Style)

  # Use URL-encoded key name for 'påkrevd_ferdighet' to avoid PowerShell quirks.
  $uri = "$base/tilgjengelige-konsulenter/sammendrag?min_tilgjengelighet_prosent=$MinAvail&p%C3%A5krevd_ferdighet=$skillEncoded&prompt_style=$styleEncoded"

  # The API uses openrouter_model for explicit override.
  # '(default)' means: do NOT override model in query string.
  if ($Model -and $Model -ne "(default)" -and $Model -ne "'(default)'" -and $Model -ne "local_gguf") {
    $modelEncoded = [System.Uri]::EscapeDataString($Model)
    $uri = $uri + "&openrouter_model=$modelEncoded"
  }

  $ts = [DateTimeOffset]::UtcNow.ToString("o")
  $sw = [System.Diagnostics.Stopwatch]::StartNew()

  $ok = $true
  $resp = $null
  $err = $null

  try {
    $resp = Invoke-RestMethod -Method GET -Uri $uri -TimeoutSec 180
  } catch {
    $ok = $false
    $err = $_.Exception.Message
  }

  $sw.Stop()

  # Extract output pieces (guarded)
  $summaryText = $null
  $meta = $null
  if ($resp -ne $null) {
    $summaryText = $resp.sammendrag
    $meta = $resp.meta
  }

  $elapsedMs = [math]::Round($sw.Elapsed.TotalMilliseconds, 2)

  # Persist *everything* needed for debugging + demo
  # IMPORTANT: emit as PSCustomObject so PSObject.Properties works reliably.
  $row = [pscustomobject]([ordered]@{
    ts = $ts
    request_url = $uri
    model = $Model
    skill = $Skill
    prompt_style = $Style
    ok = $ok

    # Keep both names to avoid future mismatch in summary code
    latency_ms  = $elapsedMs
    duration_ms = $elapsedMs

    response_sammendrag = $summaryText
    response_meta = $meta
    error = $err
  })

  # Write JSONL immediately (so partial runs still produce output)
  ($row | ConvertTo-Json -Depth 12 -Compress) | Add-Content -Path $resultsPath -Encoding UTF8

  # Print helpful console output so you can see each prompt + answer quickly
  if ($ok) {
    Write-Host ("[{0}] model={1} skill={2} style={3} ms={4}" -f $ts, $Model, $Skill, $Style, $row.latency_ms)
    if ($summaryText) {
      Write-Host ("  sammendrag: {0}" -f $summaryText)
    }
  } else {
    Write-Host ("[{0}] model={1} skill={2} style={3} FAILED ms={4}" -f $ts, $Model, $Skill, $Style, $row.latency_ms) -ForegroundColor Red
    Write-Host ("  error: {0}" -f $err) -ForegroundColor Red
  }

  return $row
}

Write-Host "";
Write-Host "Running prompt matrix..." -ForegroundColor Cyan
Write-Host ("BaseUrl      : {0}" -f $base)
Write-Host ("Skills       : {0}" -f ($Skills -join ", "))
Write-Host ("PromptStyles : {0}" -f ($PromptStyles -join ", "))
Write-Host ("Models       : {0}" -f ($Models -join ", "))
Write-Host ("Runs         : {0}" -f $Runs)
Write-Host ("OutDir       : {0}" -f (Resolve-Path $OutDir))
Write-Host ("Results JSONL: {0}" -f (Resolve-Path (Split-Path -Parent $resultsPath)))
Write-Host "";

$results = @()
foreach ($model in $Models) {
  foreach ($skill in $Skills) {
    foreach ($style in $PromptStyles) {
      for ($i = 1; $i -le $Runs; $i++) {
        $results += Invoke-Once -Skill $skill -Style $style -Model $model
        Start-Sleep -Milliseconds $DelayMs
      }
    }
  }
}

# Aggregate summary
$total = $results.Count
$passed = ($results | Where-Object { $_.ok -eq $true }).Count
$failed = $total - $passed

$fallbackUsed = ($results | Where-Object { $_.response_meta -and $_.response_meta.fallback_used -eq $true }).Count

# Robust avg latency: prefer latency_ms, fallback to duration_ms, fallback to ms
$avgLatency = 0
if ($passed -gt 0) {
  $okRows = $results | Where-Object { $_.ok -eq $true }
  $prop = Get-FirstExistingPropName -obj $okRows[0] -candidates @('latency_ms','duration_ms','ms')

  if (-not [string]::IsNullOrWhiteSpace($prop)) {
    # Use numeric values only
    $vals = @()
    foreach ($r in $okRows) {
      try {
        $v = [double]($r.$prop)
        $vals += $v
      } catch {
        # ignore non-numeric rows
      }
    }
    if ($vals.Count -gt 0) {
      $avgLatency = ($vals | Measure-Object -Average).Average
    }
  }
}

# Optional: group by provider + fallback reason (useful in interviews)
$providerBreakdown = @{}
foreach ($r in $results) {
  if ($r.ok -and $r.response_meta -and $r.response_meta.provider) {
    $p = $r.response_meta.provider
    if (-not $providerBreakdown.ContainsKey($p)) { $providerBreakdown[$p] = 0 }
    $providerBreakdown[$p] += 1
  }
}

$fallbackTop = @()
($results | Where-Object { $_.ok -and $_.response_meta -and $_.response_meta.fallback_used -eq $true }) |
  Group-Object { $_.response_meta.fallback_reason } |
  Sort-Object Count -Descending |
  Select-Object -First 10 |
  ForEach-Object {
    $fallbackTop += [ordered]@{ reason = $_.Name; count = $_.Count }
  }

$summary = [ordered]@{
  generated_at = [DateTimeOffset]::UtcNow.ToString("o")
  base_url = $base
  total = $total
  passed = $passed
  failed = $failed
  success_rate_pct = if ($total -gt 0) { [math]::Round(($passed / $total) * 100, 2) } else { 0 }
  fallback_used = $fallbackUsed
  avg_latency_ms = [math]::Round($avgLatency, 2)
  models = $Models
  skills = $Skills
  prompt_styles = $PromptStyles
  runs = $Runs
  providers = $providerBreakdown
  top_fallback_reasons = $fallbackTop
  output_results_jsonl = $resultsPath
  output_summary_json = $summaryPath
}

($summary | ConvertTo-Json -Depth 10) | Set-Content -Path $summaryPath -Encoding UTF8

Write-Host "";
Write-Host "DONE." -ForegroundColor Green
Write-Host ("Results : {0}" -f (Resolve-Path $resultsPath).Path) -ForegroundColor Green
Write-Host ("Summary  : {0}" -f (Resolve-Path $summaryPath).Path) -ForegroundColor Green
