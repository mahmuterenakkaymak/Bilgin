# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

<#
    Removes the Bilgin Windows service (PLAN R8-23).

    Run it from an elevated Windows PowerShell 5.1 or PowerShell 7:

        powershell -ExecutionPolicy Bypass -File scripts\uninstall-service.ps1

    Every step prints one "[id] ..." line. -WhatIf prints what each step would do and changes
    nothing.

    The service goes, the data root stays: the users, the stored connections, the logs and the
    sealed model keys are work nobody wants to redo for a reinstall. -RemoveData deletes the data
    root too, and even then only after an answer.

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
    [switch]$RemoveData
)

$ErrorActionPreference = 'Stop'
$script:WhatIf = [bool]$WhatIfPreference
# ASSUMPTION: the repository is the folder that holds this script; $PSScriptRoot is still empty
# inside the param block of Windows PowerShell 5.1, so the default resolves only here.
if (-not $Repo) { $Repo = Split-Path -Parent $PSScriptRoot }

$ServiceName = 'Bilgin'
$ServiceExe = Join-Path $Repo "deploy\windows\$ServiceName.exe"

function Step([string]$Id, [string]$Text) { Write-Output ('[{0}] {1}' -f $Id, $Text) }
function StepWhat([string]$Id, [string]$Text) { Write-Output ('[{0}] WHATIF {1}' -f $Id, $Text) }
function Stop([string]$Id, [string]$Text) { Write-Output ('[{0}] {1}' -f $Id, $Text); exit 1 }

# ------------------------------------------------------------------ [service]
# The one line that decides everything else: a machine that never had the service has nothing to
# remove, and the operator hears that instead of a failed stop. -WhatIf only reports the state.
$svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($script:WhatIf) {
    $state = if ($svc) { 'is installed and ' + $svc.Status } else { 'is not installed here' }
    StepWhat 'service' ('would stop and remove the service ' + $ServiceName + ', which ' + $state)
}
elseif (-not $svc) {
    Stop 'service' ('no service named ' + $ServiceName + ' on this machine - nothing to remove')
}
else {
    Step 'service' ('service ' + $ServiceName + ' found (' + $svc.Status + ')')
}

# ------------------------------------------------------------------ [stop]
if ($script:WhatIf) {
    StepWhat 'stop' ('would stop ' + $ServiceName + ' when it is running')
}
elseif ($svc.Status -eq 'Running') {
    Stop-Service -Name $ServiceName
    Step 'stop' ('service ' + $ServiceName + ' stopped')
}
else {
    Step 'stop' ('service ' + $ServiceName + ' was already ' + $svc.Status)
}

# ------------------------------------------------------------------ [uninstall]
if ($script:WhatIf) {
    StepWhat 'uninstall' ('would run: ' + $ServiceExe + ' uninstall')
}
elseif (-not (Test-Path $ServiceExe)) {
    Stop 'uninstall' ('no WinSW wrapper at ' + $ServiceExe + ' - remove the service by hand with: sc.exe delete ' +
        $ServiceName)
}
else {
    & $ServiceExe uninstall | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Stop 'uninstall' ('the service could not be removed (exit code ' + $LASTEXITCODE + ')')
    }
    Step 'uninstall' ('service ' + $ServiceName + ' removed; the wrapper under deploy\windows stays for a reinstall')
}

# ------------------------------------------------------------------ [data]
# R8-23: the data root belongs to the operator, not to the service. It survives by default, and
# -RemoveData does not delete it without an answer typed at the console.
if ($script:WhatIf) {
    if ($RemoveData) {
        StepWhat 'data' ('would ask, then delete ' + $DataHome + ' with the app database, logs, indexes and ' +
            'secrets; nothing is deleted now')
    }
    else {
        StepWhat 'data' ('would keep ' + $DataHome + ' - pass -RemoveData to delete it')
    }
}
elseif (-not $RemoveData) {
    Step 'data' ('kept ' + $DataHome + ' - pass -RemoveData to delete it too')
}
elseif (-not (Test-Path $DataHome)) {
    Step 'data' ('nothing to delete at ' + $DataHome)
}
else {
    $answer = Read-Host ('Delete ' + $DataHome + ' and everything under it? [y/N]')
    if ($answer -notin @('y', 'yes')) {
        Step 'data' ('kept ' + $DataHome + ' - the answer was not yes')
    }
    else {
        Remove-Item -LiteralPath $DataHome -Recurse -Force
        Step 'data' ('deleted ' + $DataHome)
    }
}
exit 0
