
<#############################################
traffic_generator.ps1

Small load generator to make Grafana/Prometheus dashboards come alive.

Usage:
  powershell -ExecutionPolicy Bypass -File .\scripts\traffic_generator.ps1 -Requests 200 -DelayMs 150

It hits:
  GET /tilgjengelige-konsulenter/sammendrag
with varying skills and prompt_style.
#############################################>

param(
  [string]$BaseUrl,
  [int]$Requests = 200,
  [int]$DelayMs = 150
)

$ErrorActionPreference = "Stop"

$base = $BaseUrl
if ([string]::IsNullOrWhiteSpace($base)) { $base = $env:BASE_URL }
if ([string]::IsNullOrWhiteSpace($base)) { $base = "http://localhost:8002" }

$skills = @("Python", "Azure")
$styles = @("strict", "friendly", "bullet")
$minAvail = 50

Write-Host "Generating $Requests requests against $base ..." -ForegroundColor Cyan

1..$Requests | ForEach-Object {
  $skill = $skills[(Get-Random -Minimum 0 -Maximum $skills.Count)]
  $style = $styles[(Get-Random -Minimum 0 -Maximum $styles.Count)]
  $skillEncoded = [System.Uri]::EscapeDataString($skill)
  $styleEncoded = [System.Uri]::EscapeDataString($style)
  $uri = "$base/tilgjengelige-konsulenter/sammendrag?min_tilgjengelighet_prosent=$minAvail&p%C3%A5krevd_ferdighet=$skillEncoded&prompt_style=$styleEncoded"
  try {
    Invoke-RestMethod -Method Get -Uri $uri | Out-Null
    Write-Host -NoNewline "." 
  } catch {
    Write-Host -NoNewline "E" -ForegroundColor Red
  }
  Start-Sleep -Milliseconds $DelayMs
}

Write-Host "\nDone. Open Grafana and set time range to Last 1h (or Last 15m) to see the spike." -ForegroundColor Green
