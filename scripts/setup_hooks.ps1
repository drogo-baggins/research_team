$root = Split-Path $PSScriptRoot -Parent
$hooksDir = Join-Path $root ".git\hooks"
$src = Join-Path $root "scripts\pre-commit.hook"
$dst = Join-Path $hooksDir "pre-commit"

if (-not (Test-Path $hooksDir)) {
    Write-Error "Not a git repository: $root"
    exit 1
}

Copy-Item -Path $src -Destination $dst -Force
Write-Host "pre-commit hook installed: $dst"
