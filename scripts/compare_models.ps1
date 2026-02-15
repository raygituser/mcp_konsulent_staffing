<#############################################
compare_models.ps1

Reads JSONL produced by prompt_matrix.ps1 and produces:
- out/model_comparison.json  (leaderboard + best model)

Heuristic scoring (free / offline):
1) Validity: "Fant X", mentions required skill, mentions % availability
2) Safety: no profanity/abusive language (simple deny list)
3) Prefer non-fallback
4) Prefer lower latency
5) Prefer lower cost (if present in meta)

Usage:
  powershell -ExecutionPolicy Bypass -File .\scripts\compare_models.ps1
  powershell -ExecutionPolicy Bypass -File .\scripts\compare_models.ps1 -ResultsPath .\out\prompt_matrix_results.jsonl
#############################################>

param(
  [string]$ResultsPath = ".\\out\\prompt_matrix_results.jsonl",
  [string]$OutPath = ".\\out\\model_comparison.json",

  # Weights (sum doesn't have to be 100, but that's a nice mental model)
  [double]$WValidity = 50,
  [double]$WSafety = 15,
  [double]$WNoFallback = 15,
  [double]$WLatency = 10,
  [double]$WCost = 10
)

$ErrorActionPreference = "Stop"

if (!(Test-Path $ResultsPath)) {
  throw "Results file not found: $ResultsPath (run scripts/prompt_matrix.ps1 first)"
}

# Simple safety/negativity deny list (tune to your needs)
$badWords = @(
  "idiot","stupid","hate","fuck","shit","bitch","cunt","asshole",
  "dritt","faen","jævla","helvete"
)

function Clamp([double]$x, [double]$lo, [double]$hi) {
  return [math]::Max($lo, [math]::Min($hi, $x))
}

function Score-Row($row) {
  $text = [string]$row.response_sammendrag
  $meta = $row.response_meta

  # ---------- 1) Validity ----------
  $hasFant = $text -match "Fant\s+\d+"
  $hasSkill = $false
  if ($row.skill) {
    $hasSkill = $text.ToLower().Contains(([string]$row.skill).ToLower())
  }
  $hasPercent = $text -match "\d+%"

  $validity = 0
  if ($hasFant)    { $validity += 20 }
  if ($hasSkill)   { $validity += 20 }
  if ($hasPercent) { $validity += 10 }

  # ---------- 2) Safety ----------
  $safety = 15
  foreach ($w in $badWords) {
    if ($text.ToLower().Contains($w)) {
      $safety = 0
      break
    }
  }

  # ---------- 3) Fallback ----------
  $fallback = $false
  if ($meta -and ($meta.fallback_used -eq $true)) { $fallback = $true }
  $noFallback = if ($fallback) { 0 } else { 15 }

  # ---------- 4) Latency ----------
  $lat = $null
  if ($meta -and $meta.prosessering_ms) { $lat = [double]$meta.prosessering_ms }
  elseif ($row.latency_ms) { $lat = [double]$row.latency_ms }
  elseif ($row.duration_ms) { $lat = [double]$row.duration_ms }

  # Map latency to 0..10 (<=500ms => 10, >=5000ms => 0)
  $latScore = 5
  if ($lat -ne $null) {
    if ($lat -le 500) { $latScore = 10 }
    elseif ($lat -ge 5000) { $latScore = 0 }
    else {
      $latScore = 10 * (1 - (($lat - 500) / (5000 - 500)))
      $latScore = [math]::Round((Clamp $latScore 0 10), 2)
    }
  }

  # ---------- 5) Cost ----------
  $cost = $null
  if ($meta -and ($meta.cost_credits -ne $null)) {
    $cost = [double]$meta.cost_credits
  }

  # Map cost to 0..10 (0 => 10, >=0.01 => 0). If missing => neutral 5.
  $costScore = 5
  if ($cost -ne $null) {
    if ($cost -le 0) { $costScore = 10 }
    elseif ($cost -ge 0.01) { $costScore = 0 }
    else {
      $costScore = 10 * (1 - ($cost / 0.01))
      $costScore = [math]::Round((Clamp $costScore 0 10), 2)
    }
  }

  # ---------- Weighted total ----------
  $total =
    ($validity / 50 * $WValidity) +
    ($safety / 15 * $WSafety) +
    ($noFallback / 15 * $WNoFallback) +
    ($latScore / 10 * $WLatency) +
    ($costScore / 10 * $WCost)

  return [pscustomobject]@{
    model = $row.model
    skill = $row.skill
    prompt_style = $row.prompt_style
    ok = $row.ok
    fallback_used = $fallback
    validity = $validity
    safety = $safety
    latency_ms = $lat
    cost_credits = $cost
    score = [math]::Round($total, 2)
  }
}

# Load JSONL
$rows = Get-Content $ResultsPath | Where-Object { $_ -and $_.Trim().Length -gt 0 } | ForEach-Object { $_ | ConvertFrom-Json }
$scores = $rows | ForEach-Object { Score-Row $_ }

# Aggregate by model
$byModel = $scores | Group-Object model | ForEach-Object {
  $m = $_.Name
  $items = $_.Group

  $avgScore = ($items | Measure-Object score -Average).Average
  $okRate = if ($items.Count -gt 0) { 100 * (($items | Where-Object ok).Count / $items.Count) } else { 0 }
  $fallbackRate = if ($items.Count -gt 0) { 100 * (($items | Where-Object fallback_used).Count / $items.Count) } else { 0 }

  $avgLatency = ($items | Where-Object { $_.latency_ms -ne $null } | Measure-Object latency_ms -Average).Average
  $avgCost = ($items | Where-Object { $_.cost_credits -ne $null } | Measure-Object cost_credits -Average).Average

  [pscustomobject]@{
    model = $m
    n = $items.Count
    avg_score = [math]::Round($avgScore, 2)
    ok_rate_pct = [math]::Round($okRate, 1)
    fallback_rate_pct = [math]::Round($fallbackRate, 1)
    avg_latency_ms = if ($avgLatency -ne $null) { [math]::Round($avgLatency, 1) } else { $null }
    avg_cost_credits = if ($avgCost -ne $null) { [math]::Round($avgCost, 6) } else { $null }
  }
} | Sort-Object avg_score -Descending

$best = $byModel | Select-Object -First 1

$out = [pscustomobject]@{
  generated_at = (Get-Date).ToString("o")
  results_path = (Resolve-Path $ResultsPath).Path
  best_model = $best
  leaderboard = $byModel
}

# Ensure output dir exists
$parent = Split-Path -Parent $OutPath
if ($parent -and !(Test-Path $parent)) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }

$out | ConvertTo-Json -Depth 8 | Set-Content -Path $OutPath -Encoding UTF8

Write-Host "Wrote comparison:" (Resolve-Path $OutPath).Path
Write-Host "Best model:" $best.model " avg_score=" $best.avg_score
