# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

<#
    Restarts the Bilgin Windows service after the code changed (PLAN R8-23).

        powershell -ExecutionPolicy Bypass -File scripts\update-service.ps1

    Every step prints one "[id] ..." line. -WhatIf prints what each step would do and changes
    nothing.

    The code itself is not touched: the operator brings the new version over between the stop and
    the start, this script never fetches anything. The only build it runs is the UI, and only when
    a file under web\ is newer than the built bilgin\web\static\index.html - a Python-only update
    costs no build.

    The file is ASCII only: Windows PowerShell 5.1 reads a script without a byte-order mark in
    the console's own code page, so a Turkish character in a message would arrive as mojibake.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$Repo = '',
    # $Home is a read-only automatic variable of PowerShell, so the parameter is called Home and
    # the variable behind it is not.
    [Alias('Home')]
    [string]$DataHome = 'C:\ProgramData\Bilgin',
    [ValidateRange(1, 65535)][int]$Port = 8777
)

$ErrorActionPreference = 'Stop'
$script:WhatIf = [bool]$WhatIfPreference
# ASSUMPTION: the repository is the folder that holds this script; $PSScriptRoot is still empty
# inside the param block of Windows PowerShell 5.1, so the default resolves only here.
if (-not $Repo) { $Repo = Split-Path -Parent $PSScriptRoot }

$ServiceName = 'Bilgin'
$ServiceExe = Join-Path $Repo "deploy\windows\$ServiceName.exe"
$WebDir = Join-Path $Repo 'web'
$IndexHtml = Join-Path $Repo 'bilgin\web\static\index.html'
$ViteJs = Join-Path $Repo 'web\node_modules\vite\bin\vite.js'
$HealthUrl = "http://127.0.0.1:$Port/api/health"

function Step([string]$Id, [string]$Text) { Write-Output ('[{0}] {1}' -f $Id, $Text) }
function StepWhat([string]$Id, [string]$Text) { Write-Output ('[{0}] WHATIF {1}' -f $Id, $Text) }
function Stop([string]$Id, [string]$Text) { Write-Output ('[{0}] {1}' -f $Id, $Text); exit 1 }

# The sources of the UI, newest-first irrelevant: only the count and one example are printed.
# node_modules lives under web\ and its timestamps move on every package install, so it is walked
# around instead of filtered out afterwards - it holds more files than the whole source tree.
function Get-NewerSources([string]$Root, [datetime]$Limit) {
    $found = @()
    if (-not (Test-Path -LiteralPath $Root)) { return $found }
    $stack = [System.Collections.Generic.Stack[string]]::new()
    $stack.Push($Root)
    while ($stack.Count -gt 0) {
        $dir = $stack.Pop()
        foreach ($file in [System.IO.Directory]::GetFiles($dir)) {
            if ([System.IO.File]::GetLastWriteTimeUtc($file) -gt $Limit) { $found += $file }
        }
        foreach ($child in [System.IO.Directory]::GetDirectories($dir)) {
            if ((Split-Path -Leaf $child) -ne 'node_modules') { $stack.Push($child) }
        }
    }
    $found
}

# ------------------------------------------------------------------ [service]
$svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($script:WhatIf) {
    $state = if ($svc) { 'is installed and ' + $svc.Status } else { 'is not installed here' }
    StepWhat 'service' ('would stop and start the service ' + $ServiceName + ', which ' + $state)
}
elseif (-not $svc) {
    Stop 'service' ('no service named ' + $ServiceName + ' on this machine - run scripts\install-service.ps1 first')
}
elseif (-not (Test-Path $ServiceExe)) {
    Stop 'service' ('the service is installed but its WinSW wrapper is missing at ' + $ServiceExe)
}
else {
    Step 'service' ('service ' + $ServiceName + ' found (' + $svc.Status + ')')
}

# ------------------------------------------------------------------ [stop]
# The build writes into the package the service serves, so it runs while the service is down.
if ($script:WhatIf) {
    StepWhat 'stop' ('would stop ' + $ServiceName + ' when it is running')
}
elseif ($svc.Status -eq 'Running') {
    & $ServiceExe stop | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Stop 'stop' ('the service did not stop (exit code ' + $LASTEXITCODE + ')')
    }
    Step 'stop' ('service ' + $ServiceName + ' stopped')
}
else {
    Step 'stop' ('service ' + $ServiceName + ' was already ' + $svc.Status)
}

# ------------------------------------------------------------------ [ui]
$built = if (Test-Path -LiteralPath $IndexHtml) {
    [System.IO.FileInfo]::new($IndexHtml).LastWriteTimeUtc
} else {
    [datetime]::MinValue
}
$sources = @(Get-NewerSources $WebDir $built)
if ($sources.Count -eq 0) {
    Step 'ui' ('the built UI is current - no file under ' + $WebDir + ' is newer than ' + $IndexHtml)
}
elseif ($script:WhatIf) {
    StepWhat 'ui' ('ui rebuild: ' + $sources.Count + ' file(s) under web\ are newer than ' + $IndexHtml +
        ' (for example ' + $sources[0] + '); would run node ' + $ViteJs + ' build web --config web\vite.config.js')
}
else {
    if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
        Stop 'ui' ('node is not on PATH - build the UI by hand and run this script again')
    }
    Step 'ui' ('ui rebuild: ' + $sources.Count + ' file(s) under web\ are newer than ' + $IndexHtml)
    Push-Location $Repo
    try {
        & node 'web\node_modules\vite\bin\vite.js' build web --config web\vite.config.js
        $code = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
    if ($code -ne 0) {
        Stop 'ui' ('the UI build failed (exit code ' + $code + ') - the service is still stopped')
    }
    Step 'ui' ('rebuilt the UI into ' + (Split-Path -Parent $IndexHtml))
}

# ------------------------------------------------------------------ [start]
if ($script:WhatIf) {
    StepWhat 'start' ('would run: ' + $ServiceExe + ' start')
}
else {
    & $ServiceExe start | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Stop 'start' ('the service did not start (exit code ' + $LASTEXITCODE + ') - see ' +
            (Join-Path $DataHome 'logs'))
    }
    Step 'start' ('service ' + $ServiceName + ' started')
}

# ------------------------------------------------------------------ [health]
if ($script:WhatIf) {
    StepWhat 'health' ('would poll ' + $HealthUrl + ' for up to 60 s')
}
else {
    $deadline = (Get-Date).AddSeconds(60)
    $healthy = $false
    while ((Get-Date) -lt $deadline) {
        try {
            if ((Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 5).StatusCode -eq 200) {
                $healthy = $true
                break
            }
        } catch { }
        Start-Sleep -Seconds 2
    }
    if (-not $healthy) {
        Stop 'health' ($HealthUrl + ' did not answer within 60 s - look at ' + (Join-Path $DataHome 'logs'))
    }
    Step 'health' 'the service answers /api/health'
}
exit 0
