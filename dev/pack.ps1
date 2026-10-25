# Builds dist\Teksting.zip for the end user: code only, CRLF for .bat/.vbs/.ps1/.txt.
# Run: powershell -ExecutionPolicy Bypass -File dev\pack.ps1
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$dist = Join-Path $root 'dist'
$zip = Join-Path $dist 'Teksting.zip'

$files = @('server.py', 'requirements.txt', 'start.bat', 'Teksting.vbs', 'lag-snarveier.ps1', 'LES MEG.txt')
$files += Get-ChildItem (Join-Path $root 'tekst') -File -Filter *.py | ForEach-Object { "tekst/$($_.Name)" }
$files += Get-ChildItem (Join-Path $root 'static') -File | ForEach-Object { "static/$($_.Name)" }

New-Item -ItemType Directory -Force $dist | Out-Null
if (Test-Path $zip) { Remove-Item $zip }

Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
$archive = [IO.Compression.ZipFile]::Open($zip, 'Create')
try {
  foreach ($rel in $files) {
    $src = Join-Path $root $rel
    if (-not (Test-Path $src)) { throw "Missing: $rel" }
    $bytes = [IO.File]::ReadAllBytes($src)
    if ($rel -match '\.(bat|vbs|ps1|txt)$') {
      # Windows scripts must have CRLF line endings or cmd/wscript misbehave
      $text = [Text.Encoding]::UTF8.GetString($bytes) -replace "`r`n", "`n" -replace "`n", "`r`n"
      $bytes = [Text.Encoding]::UTF8.GetBytes($text)
    }
    $entry = $archive.CreateEntry("Teksting/$rel")   # forward slashes, one top folder
    $s = $entry.Open(); $s.Write($bytes, 0, $bytes.Length); $s.Close()
  }
  # which commit this is, so the app's updater (tekst/update.py) knows what it runs
  $sha = (git -C $root rev-parse HEAD).Trim()
  $entry = $archive.CreateEntry('Teksting/version.txt')
  $s = $entry.Open(); $b = [Text.Encoding]::ASCII.GetBytes($sha); $s.Write($b, 0, $b.Length); $s.Close()
} finally { $archive.Dispose() }

Write-Host "Built $zip ($($files.Count) files, $([math]::Round((Get-Item $zip).Length / 1KB)) KB)"
