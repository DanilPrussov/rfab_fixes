[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Mo2Root
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$name = 'RFAB-ShockNova-NeutralTargets.esp'
$sourceHash = 'a5b03f58aeefeb806f7c4e44981d4f3ba0bc125419d488d3fcc7a896768d3401'
$patchHash = '640c860aca45858c89946ecc34a92a178022428f8d3e060ced1edc4a68d94994'
$source = Join-Path $Mo2Root 'mods\RFAB\RFAB.esp'
$payload = Join-Path $PSScriptRoot 'payload'
$patch = Join-Path $payload $name
$repo = (Get-Item -LiteralPath $PSScriptRoot).Parent.Parent.FullName
$destination = Join-Path $repo 'dist'
$archive = Join-Path $destination '0001-shock-nova-neutral-targets.zip'

function Assert-Hash([string]$Path, [string]$Expected) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "File not found: $Path"
    }
    $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $Expected) {
        throw "SHA-256 mismatch: $Path`nExpected: $Expected`nActual: $actual`nStop: this file needs a new review."
    }
}

function Test-Package([string]$Path) {
    $zip = [System.IO.Compression.ZipFile]::OpenRead($Path)
    try {
        if ($zip.Entries.Count -ne 1 -or $zip.Entries[0].FullName -cne $name) {
            throw "Unexpected ZIP content: $Path"
        }
        $stream = $zip.Entries[0].Open()
        $sha = [System.Security.Cryptography.SHA256]::Create()
        try {
            $actual = ([BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-', '').ToLowerInvariant()
            if ($actual -ne $patchHash) { throw "Unexpected ESP bytes in ZIP: $Path" }
        }
        finally {
            $stream.Dispose()
            $sha.Dispose()
        }
    }
    finally { $zip.Dispose() }
}

Assert-Hash $source $sourceHash
Assert-Hash $patch $patchHash
$files = @(Get-ChildItem -LiteralPath $payload -File -Recurse -Force |
    Where-Object { $_.Name -ne '.gitkeep' })
if ($files.Count -ne 1 -or $files[0].FullName -ne (Get-Item -LiteralPath $patch).FullName) {
    throw 'Payload must contain only the reviewed ESP.'
}

Add-Type -AssemblyName System.IO.Compression.FileSystem
if (Test-Path -LiteralPath $archive) {
    Test-Package $archive
    Write-Host "Existing verified archive: $archive"
}
else {
    New-Item -ItemType Directory -Path $destination -Force | Out-Null
    Compress-Archive -LiteralPath $patch -DestinationPath $archive
    Test-Package $archive
    Write-Host "Created and verified archive: $archive"
}
Write-Host 'Install this ZIP in a separate MO2 test profile.'
Write-Host "Enable the mod and $name. Load it after RFAB.esp."
Write-Host 'Game test pending. Use a copy of a save made before the incident.'
