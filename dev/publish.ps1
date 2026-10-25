# Publishes the current commit as the new version: every installed Teksting downloads it in the background
# and uses it from its next start (tekst/update.py). Also builds dist\Teksting.zip for new installs.
# Run: powershell -ExecutionPolicy Bypass -File dev\publish.ps1
# To undo a bad release: git revert it and publish again (installed copies never go back to an older commit).
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root
function Check($what) { if ($LASTEXITCODE -ne 0) { throw "$what failed: nothing published." } }

if (git status --porcelain) { throw 'Uncommitted changes: commit them first (only committed code is published).' }
$py = (Get-ChildItem 'runtime\python\cpython-3.12*\python.exe' | Select-Object -First 1).FullName
& $py -m compileall -q server.py tekst; Check 'Syntax check'
& cmd /c "dev\test.bat"; Check 'Tests'
git push origin HEAD; Check 'Push'
git push --force origin HEAD:release; Check 'Push to the release branch'
& powershell -ExecutionPolicy Bypass -File (Join-Path $root 'dev\pack.ps1'); Check 'Building the zip'
Write-Host "Published $(git rev-parse --short HEAD). Installed copies pick it up within 6 hours or at their next start."
