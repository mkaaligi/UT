<#
.SYNOPSIS
    Renders a worklist of VIs to content-addressed HTML snapshots inside a
    LabVIEW Windows container.
#>
param(
    [string]$WorkspaceRoot = 'C:\workspace',
    [string]$OpsDir        = 'C:\ops',
    [string]$OutByBlobDir  = 'C:\out\by-blob',
    [string]$WorkListPath  = 'C:\out\worklist.tsv',
    [string]$LabVIEWPath   = '',
    [string]$EmitFramesJson = 'true'
)

$ErrorActionPreference = 'Stop'
$ProgressPreference    = 'SilentlyContinue'

function Resolve-LabVIEWPath([string]$PreferredPath) {
    if ($PreferredPath -and (Test-Path $PreferredPath)) { return $PreferredPath }
    $candidates = @(Get-ChildItem 'C:\Program Files\National Instruments' -Directory -Filter 'LabVIEW *' -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending |
        ForEach-Object { Join-Path $_.FullName 'LabVIEW.exe' } |
        Where-Object { Test-Path $_ })
    if ($candidates.Count -gt 0) { return $candidates[0] }
    throw "LabVIEW.exe not found."
}

function Resolve-LabVIEWCLI([string]$LabVIEWExePath) {
    $cliCmd = Get-Command LabVIEWCLI.exe -ErrorAction SilentlyContinue
    if ($null -eq $cliCmd) { $cliCmd = Get-Command LabVIEWCLI -ErrorAction SilentlyContinue }
    if ($null -ne $cliCmd -and $cliCmd.Source) { return $cliCmd.Source }
    $candidate = Join-Path (Split-Path $LabVIEWExePath) 'LabVIEWCLI.exe'
    if (Test-Path $candidate) { return $candidate }
    throw "LabVIEWCLI not found."
}

function Write-Placeholder([string]$Path, [string]$Rel, [string]$Reason) {
    $dir = Split-Path $Path
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $safeRel    = $Rel    -replace '&','&amp;' -replace '<','&lt;' -replace '>','&gt;'
    $safeReason = $Reason -replace '&','&amp;' -replace '<','&lt;' -replace '>','&gt;'
    $html = @"
<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>Snapshot unavailable</title>
<style>body{margin:0;padding:24px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0d1117;color:#e6edf3}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:20px;max-width:680px}
h1{font-size:1.1em;margin:0 0 8px}.muted{color:#8b949e;font-size:.85em}</style></head>
<body><div class="card"><h1>Snapshot unavailable</h1>
<div class="muted">$safeRel</div><p class="muted">$safeReason</p></div></body></html>
"@
    [System.IO.File]::WriteAllText($Path, $html, [System.Text.UTF8Encoding]::new($false))
}

function Enable-LVScripting([string]$LabVIEWExePath) {
    $iniPath = Join-Path (Split-Path -Parent $LabVIEWExePath) 'LabVIEW.ini'
    $tokens  = [ordered]@{
        'SuperSecretPrivateSpecialStuff'    = 'True'
        'unattended'                        = 'True'
        'AllowMultipleInstances'            = 'True'
        'SaveChangesAutoSelection'          = 'dont'
        'SaveChanges_ApplyToAll'            = 'True'
        'AutoSaveEnabled'                   = 'False'
        'neverShowLicensingStartupDialog'   = 'True'
        'neverShowAddonLicensingStartup'    = 'True'
        'SuppressRTConnectionDialogs'       = 'True'
        'DeployDlgCloseWindow'              = 'True'
        'DWarnDialog'                       = 'False'
        'nirviShowErrorDialogs'             = 'False'
        'nirviShowErrorDialogsOld'          = 'False'
        'NIERAutoSendAndSuppressAllDialogs' = 'True'
        'NIERShowFatalDialog'               = '0'
        'NIERSendDialogClose'               = 'True'
        'NIERShowNonFatalDialogOnExit'      = 'False'
        'autoerr'                           = '3'
    }
    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    $existing = @()
    if (Test-Path -LiteralPath $iniPath) { $existing = @(Get-Content -LiteralPath $iniPath) }
    $secIdx = -1
    for ($i = 0; $i -lt $existing.Count; $i++) {
        if ("$($existing[$i])".Trim() -ieq '[LabVIEW]') { $secIdx = $i; break }
    }
    if ($secIdx -lt 0) {
        $block = @('[LabVIEW]') + ($tokens.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" })
        if ($existing.Count -gt 0 -and "$($existing[-1])".Trim() -ne '') { $existing += '' }
        $existing += $block
        [System.IO.File]::WriteAllLines($iniPath, [string[]]$existing, $utf8NoBom)
        Write-Host "  Scripting: created [LabVIEW] section in $iniPath"
        return
    }
    $end = $existing.Count
    for ($j = $secIdx + 1; $j -lt $existing.Count; $j++) {
        if ("$($existing[$j])" -match '^\s*\[.+\]\s*$') { $end = $j; break }
    }
    $pre  = @(); if ($secIdx -ge 0)            { $pre  = @($existing[0..$secIdx]) }
    $body = @(); if ($end -gt ($secIdx + 1))   { $body = @($existing[($secIdx + 1)..($end - 1)]) }
    $post = @(); if ($end -lt $existing.Count) { $post = @($existing[$end..($existing.Count - 1)]) }
    foreach ($key in $tokens.Keys) {
        $val   = $tokens[$key]
        $found = $false
        for ($k = 0; $k -lt $body.Count; $k++) {
            if ("$($body[$k])" -match "^\s*$([regex]::Escape($key))\s*=") { $body[$k] = "$key=$val"; $found = $true; break }
        }
        if (-not $found) { $body += "$key=$val" }
    }
    $merged = @(); $merged += $pre; $merged += $body; $merged += $post
    [System.IO.File]::WriteAllLines($iniPath, [string[]]$merged, $utf8NoBom)
}

$ResolvedLV = Resolve-LabVIEWPath $LabVIEWPath
$CliExe     = Resolve-LabVIEWCLI $ResolvedLV
$OpClass = Join-Path $OpsDir 'PrintToSingleFileHtml'
if (-not (Test-Path $OpClass)) {
    Write-Error "PrintToSingleFileHtml operation not found under '$OpsDir'."
    exit 1
}

$ImagesOp     = Join-Path $OpsDir 'PrintToImagesJson'
$HaveImagesOp = (Test-Path $ImagesOp) -and ($EmitFramesJson -ne 'false')

if ($HaveImagesOp) {
    try { Enable-LVScripting $ResolvedLV }
    catch { Write-Warning "  Could not update LabVIEW.ini for scripting: $_ (JSON capture may fail)." }
}

Write-Host "=== Render VI Snapshots ==="
Write-Host "  Workspace : $WorkspaceRoot"
Write-Host "  LabVIEW   : $ResolvedLV"
Write-Host "  CLI       : $CliExe"
Write-Host "  Ops       : $OpsDir"
Write-Host "  Out       : $OutByBlobDir"

if (-not (Test-Path $WorkListPath)) {
    Write-Host "  Worklist is empty - nothing to render."
    exit 0
}

$lines = Get-Content $WorkListPath | Where-Object { $_.Trim() -ne '' }
Write-Host "  Worklist  : $($lines.Count) VI(s)"
Write-Host ""

$Rendered = 0; $Skipped = 0; $Errors = 0
$ErrorActionPreference = 'Continue'

foreach ($line in $lines) {
    $parts = $line -split "`t", 2
    if ($parts.Count -ne 2) { continue }
    $blob = $parts[0].Trim()
    $rel  = $parts[1].Trim()
    if ($blob.Length -lt 2 -or $rel -eq '') { continue }

    $OutDir  = Join-Path $OutByBlobDir $blob.Substring(0, 2)
    $OutFile = Join-Path $OutDir ($blob + '.html')
    if (Test-Path $OutFile) { $Skipped++; continue }

    $ViPath = Join-Path $WorkspaceRoot ($rel -replace '/', '\')
    if (-not (Test-Path $ViPath)) {
        Write-Warning "  MISSING: $rel"
        Write-Placeholder -Path $OutFile -Rel $rel -Reason 'VI file not found in commit tree.'
        $Errors++
        continue
    }

    New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

    try {
        & $CliExe `
            -OperationName                PrintToSingleFileHtml `
            -LabVIEWPath                  $ResolvedLV `
            -AdditionalOperationDirectory $OpsDir `
            -LogToConsole                 TRUE `
            -VI                           $ViPath `
            -OutputPath                   $OutFile `
            -o -c `
            -Headless
        if ($LASTEXITCODE -ne 0) { throw "exit code $LASTEXITCODE" }
        if (-not (Test-Path $OutFile)) { throw 'no output produced' }
        Write-Host "  OK: $rel"
        $Rendered++

        if ($HaveImagesOp) {
            $JsonOut = [System.IO.Path]::ChangeExtension($OutFile, '.json')
            try {
                & $CliExe `
                    -OperationName                PrintToImagesJson `
                    -LabVIEWPath                  $ResolvedLV `
                    -AdditionalOperationDirectory $OpsDir `
                    -LogToConsole                 TRUE `
                    -VI                           $ViPath `
                    -OutputPath                   $JsonOut `
                    -o -c `
                    -Headless
                if ($LASTEXITCODE -eq 0 -and (Test-Path $JsonOut)) { Write-Host "  JSON: $rel" }
                else { Write-Warning "  (json) skipped for $rel (op exit $LASTEXITCODE)" }
            } catch {
                Write-Warning "  (json) error for $rel - $_ (non-fatal)"
            }
        }
    } catch {
        Write-Warning "  ERROR: $rel - $_"
        Write-Placeholder -Path $OutFile -Rel $rel -Reason "Render failed: $_"
        $Errors++
    }
}

Write-Host ""
Write-Host "=== Render complete: $Rendered rendered, $Skipped skipped, $Errors errors ==="
exit 0
