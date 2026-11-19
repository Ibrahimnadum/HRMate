# Copies the project to the NAS and rebuilds the container.
#   .\scripts\deploy-nas.ps1                 update the code and rebuild
#   .\scripts\deploy-nas.ps1 -ImportLegacy   also import import\legacy.sqlite (old program history)
param(
    [string]$Nas = "192.168.5.18",
    [string]$User = "it-admin",
    [switch]$ImportLegacy
)
$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
$Target = "\\$Nas\docker\attendance"
$Docker = "sudo /usr/local/bin/docker"

# Sign in to the NAS share once per Windows session, if needed.
$Share = "\\$Nas\docker"
if (-not (Test-Path $Share)) {
    Write-Host "Signing in to $Share as $User (DSM password) ..."
    & net use $Share /user:$User *
    if ($LASTEXITCODE -ne 0) { throw "Could not sign in to $Share." }
}

# data\ on the NAS holds the database: never copied over or deleted.
& robocopy $Root $Target /MIR /XD data import .git __pycache__ node_modules dist /XF "*.pyc" "*.zip" /NFL /NDL /NJH /NP
if ($LASTEXITCODE -ge 8) { throw "Copy to $Target failed ($LASTEXITCODE)." }
Write-Host "Code copied to $Target."

$steps = "cd /volume1/docker/attendance && mkdir -p data && $Docker compose up -d --build"
if ($ImportLegacy) {
    $file = Join-Path $Root "import\legacy.sqlite"
    if (-not (Test-Path $file)) { throw "Missing $file" }
    New-Item -ItemType Directory -Force "$Target\data\import" | Out-Null
    Copy-Item $file "$Target\data\import\legacy.sqlite" -Force
    Write-Host "Copied legacy.sqlite to the NAS."
    $steps += " && sleep 5 && $Docker compose exec -T att python -m app.manage import-legacy /data/import/legacy.sqlite"
}
$steps += " && $Docker compose ps"

Write-Host "Building on the NAS (the first build takes several minutes) ..."
ssh -t "$User@$Nas" $steps
if ($LASTEXITCODE -ne 0) { throw "The build on the NAS failed." }
Write-Host "Done. Open http://${Nas}:8090"
