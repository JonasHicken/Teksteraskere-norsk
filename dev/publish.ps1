# Publishes the current commit as the new version: every installed Teksting downloads it in the background
# and uses it from its next start (tekst/update.py). Also builds dist\Teksting.zip for new installs.
# Run: powershell -ExecutionPolicy Bypass -File dev\publish.ps1
#      add -NoNotes only when the owner wants this update to go out without release notes
param([switch]$NoNotes)
# To undo a bad release: git revert it and publish again (installed copies never go back to an older commit).
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root
function Check($what) { if ($LASTEXITCODE -ne 0) { throw "$what failed: nothing published." } }

if (git status --porcelain) { throw 'Uncommitted changes: commit them first (only committed code is published).' }
# Every update comes with release notes: static/changelog.json must start with an entry newer than the release's.
git fetch -q origin release; Check 'Fetching the release branch'
$now = (Get-Content -Raw -Encoding UTF8 'static\changelog.json' | ConvertFrom-Json)[0].n
$was = 0
try { $old = git show origin/release:static/changelog.json 2>$null } catch { $old = $null }  # none before update 5
if ($LASTEXITCODE -eq 0 -and $old) { $was = (($old -join "`n") | ConvertFrom-Json)[0].n }
if ($now -le $was -and -not $NoNotes) { throw "No release notes: add update $($was + 1) at the top of static\changelog.json." }
$py = (Get-ChildItem 'runtime\python\cpython-3.12*\python.exe' | Select-Object -First 1).FullName
& $py -m compileall -q server.py tekst; Check 'Syntax check'
& cmd /c "dev\test.bat"; Check 'Tests'
git push origin HEAD; Check 'Push'
git push --force origin HEAD:release; Check 'Push to the release branch'
& powershell -ExecutionPolicy Bypass -File (Join-Path $root 'dev\pack.ps1'); Check 'Building the zip'
Write-Host "Published $(git rev-parse --short HEAD). Installed copies pick it up within 6 hours or at their next start."
