$ErrorActionPreference = "SilentlyContinue"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$projectLogDir = Join-Path $root "logs"
$nvdaLogDir = Join-Path $env:APPDATA "nvda\nvdastudio_logs"

foreach ($dir in @($projectLogDir, $nvdaLogDir)) {
  if (Test-Path -LiteralPath $dir) {
    Get-ChildItem -LiteralPath $dir -File -Include *.log,*.err,*.out -Recurse |
      Remove-Item -Force
  }
}

Get-ChildItem -LiteralPath $root -Directory -Recurse -Force -Filter "__pycache__" |
  Where-Object { $_.FullName -notmatch "\\(\.git|\.venv|node_modules)\\" } |
  Remove-Item -Recurse -Force

foreach ($path in @(".pytest_cache", ".mypy_cache", ".ruff_cache", ".coverage", "coverage.json", "coverage.xml")) {
  $target = Join-Path $root $path
  if (Test-Path -LiteralPath $target) {
    Remove-Item -LiteralPath $target -Recurse -Force
  }
}
