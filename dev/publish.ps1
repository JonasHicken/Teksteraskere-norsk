# Publishes the current commit as the new version: every installed Teksting downloads it in the background
# and uses it from its next start (tekst/update.py). Also builds dist\Teksting.zip for new installs.
# Run: powershell -ExecutionPolicy Bypass -File dev\publish.ps1
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

if (git status --porcelain) { throw 'Uncommitted changes: commit them first (only committed code is published).' }
& cmd /c "dev\test.bat"
if ($LASTEXITCODE -ne 0) { throw 'Tests failed: nothing published.' }
git push origin HEAD
git push --force origin HEAD:release
if ($LASTEXITCODE -ne 0) { throw 'Push to the release branch failed.' }
& powershell -ExecutionPolicy Bypass -File (Join-Path $root 'dev\pack.ps1')
Write-Host "Published $(git rev-parse --short HEAD). Installed copies pick it up within 6 hours or at their next start."
