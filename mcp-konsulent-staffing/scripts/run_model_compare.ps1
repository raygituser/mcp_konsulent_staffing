<#############################################
run_model_compare.ps1

Convenience wrapper that:
  1) runs scripts/prompt_matrix.ps1 for multiple models
  2) runs scripts/compare_models.ps1 to produce a leaderboard

This avoids PowerShell multiline / backtick issues by letting you pass arrays
in a single line.
#############################################>

param(
  [string]$BaseUrl = "http://localhost:8002",
  [string[]]$Models = @(
    "openrouter:mistralai/mistral-small-3.1-24b-instruct:free",
    "tngtech/deepseek-r1t2-chimera:free"
  ),
  [string[]]$Skills = @("Python", "Azure"),
  [string[]]$PromptStyles = @("strict", "friendly"),
  [int]$Runs = 2,
  [int]$MinAvail = 50,
  [int]$DelayMs = 300,
  [string]$OutDir = ".\\out"
)

$ErrorActionPreference = "Stop"

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$promptMatrix = Join-Path $here "prompt_matrix.ps1"
$compareModels = Join-Path $here "compare_models.ps1"

Write-Host "Running prompt matrix for models: $($Models -join ', ')" -ForegroundColor Cyan

& powershell -ExecutionPolicy Bypass -File $promptMatrix \
  -BaseUrl $BaseUrl \
  -Models $Models \
  -Skills $Skills \
  -PromptStyles $PromptStyles \
  -Runs $Runs \
  -MinAvail $MinAvail \
  -DelayMs $DelayMs \
  -OutDir $OutDir

Write-Host "Ranking models..." -ForegroundColor Cyan

& powershell -ExecutionPolicy Bypass -File $compareModels \
  -ResultsPath (Join-Path $OutDir "prompt_matrix_results.jsonl") \
  -OutPath (Join-Path $OutDir "model_comparison.json")

Write-Host "Done. Open out/model_comparison.json for the leaderboard." -ForegroundColor Green
