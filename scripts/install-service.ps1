<#
    Installs the Bilgin Windows service (PLAN R8-23).

    Run it from an elevated Windows PowerShell 5.1 or PowerShell 7:

        powershell -ExecutionPolicy Bypass -File scripts\install-service.ps1 -Home C:\ProgramData\Bilgin

    Every step prints one "[id] ..." line. -WhatIf prints what each step would do, plus the
    generated WinSW XML, and changes and downloads nothing.

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
    [ValidateRange(1, 65535)][int]$Port = 8777,
    [string]$Dataset = 'synthetic_erp',
    [ValidateSet('tr', 'en')][string]$Lang = 'tr',
    [ValidateSet('sqlite', 'mssql')][string]$Backend = 'sqlite',
    [switch]$CopyAppDb
)

$ErrorActionPreference = 'Stop'
$script:WhatIf = [bool]$WhatIfPreference
# ASSUMPTION: the repository is the folder that holds this script; $PSScriptRoot is still empty
# inside the param block of Windows PowerShell 5.1, so the default resolves only here.
if (-not $Repo) { $Repo = Split-Path -Parent $PSScriptRoot }

# The one pinned WinSW release (R8-23). The hash is copied by hand from the official release
# page; while it is empty the script refuses to install anything.
$WinSwVersion = '2.12.0'
$WinSwUrl = "https://github.com/winsw/winsw/releases/download/v$WinSwVersion/WinSW-x64.exe"
$WinSwSha256 = ''

$ServiceName = 'Bilgin'
$ServiceAccount = "NT SERVICE\$ServiceName"
$Administrators = 'BUILTIN\Administrators'
$PythonExe = Join-Path $Repo '.venv\Scripts\python.exe'
$WinSwExe = Join-Path $Repo 'deploy\windows\WinSW-x64.exe'
$ServiceExe = Join-Path $Repo "deploy\windows\$ServiceName.exe"
$ServiceXml = Join-Path $Repo "deploy\windows\$ServiceName.xml"
$AppDb = Join-Path $DataHome 'data\bilgin.db'
$SecretsDir = Join-Path $DataHome 'secrets'
$HealthUrl = "http://127.0.0.1:$Port/api/health"

# The service has no environment of its own; the child commands of the install run against the
# data root the service is about to get, so the app DB and the secrets folder are the right ones.
# The backend goes the same way: service-xml writes the NL2SQL_BACKEND the service starts with.
$env:NL2SQL_HOME = $DataHome
$env:NL2SQL_BACKEND = $Backend

function Step([string]$Id, [string]$Text) { Write-Output ('[{0}] {1}' -f $Id, $Text) }
function StepWhat([string]$Id, [string]$Text) { Write-Output ('[{0}] WHATIF {1}' -f $Id, $Text) }
function Stop([string]$Id, [string]$Text) { Write-Output ('[{0}] {1}' -f $Id, $Text); exit 1 }

function Test-Elevated {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    (New-Object Security.Principal.WindowsPrincipal $id).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}

# ------------------------------------------------------------------ [admin]
if ($script:WhatIf) {
    StepWhat 'admin' 'needs an elevated shell; would refuse when it is not one'
}
elseif (-not (Test-Elevated)) {
    Stop 'admin' 'not running as administrator - run this script from an elevated shell'
}
else {
    Step 'admin' 'running as administrator'
}

# ------------------------------------------------------------------ [dev-admin-env]
# R8-23: the development bootstrap password must never reach the service. The install refuses
# while it exists at machine or process level instead of silently inheriting it.
$devAdmin = [Environment]::GetEnvironmentVariable('NL2SQL_DEV_ADMIN_PASSWORD', 'Machine')
if (-not $devAdmin) {
    $devAdmin = [Environment]::GetEnvironmentVariable('NL2SQL_DEV_ADMIN_PASSWORD', 'Process')
}
if ($devAdmin) {
    Stop 'dev-admin-env' ('NL2SQL_DEV_ADMIN_PASSWORD is set - unset it (machine and shell) and ' +
        'run the install again; the first administrator is created interactively below')
}
Step 'dev-admin-env' 'NL2SQL_DEV_ADMIN_PASSWORD is not set'

# ------------------------------------------------------------------ [shell]
$major = [int]$PSVersionTable.PSVersion.Major
if ($major -notin 5, 6, 7) {
    Stop 'shell' ('Windows PowerShell 5.1 or PowerShell 7 is needed, found ' + $PSVersionTable.PSVersion)
}
Step 'shell' ('PowerShell ' + $PSVersionTable.PSVersion)

# ------------------------------------------------------------------ [venv]
if ($script:WhatIf) {
    StepWhat 'venv' ('would require ' + $PythonExe)
}
elseif (-not (Test-Path $PythonExe)) {
    Stop 'venv' ('no virtualenv at ' + $PythonExe + ' - create it and install the dependencies first')
}
else {
    Step 'venv' $PythonExe
}

# ------------------------------------------------------------------ [port]
if ($script:WhatIf) {
    StepWhat 'port' ('would check that 127.0.0.1:' + $Port + ' is free')
}
else {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
    $free = $true
    try { $listener.Start() } catch { $free = $false } finally { $listener.Stop() }
    if (-not $free) {
        Stop 'port' ('127.0.0.1:' + $Port + ' is taken - free it or pass another -Port')
    }
    Step 'port' ('127.0.0.1:' + $Port + ' is free')
}

# ------------------------------------------------------------------ [model] [connection]
# Both come from the program's own probe (R8-23): a closed endpoint or a login that can write is
# the operator's to fix, so each one is a warning, never a refusal.
$check = $null
if (-not $script:WhatIf) {
    try {
        $check = & $PythonExe -m nl2sql service-check --dataset $Dataset --json 2>$null |
            Out-String | ConvertFrom-Json
    } catch { $check = $null }
}
if ($script:WhatIf) {
    StepWhat 'model' 'would ask service-check whether the model endpoint answers (warning only)'
}
elseif ($null -eq $check) {
    Step 'model' 'WARNING service-check could not run - start the model endpoint or ignore this'
}
elseif ($check.model.ok) {
    Step 'model' $check.model.message
}
else {
    Step 'model' ('WARNING ' + $check.model.message)
}

if ($script:WhatIf) {
    StepWhat 'connection' 'would run the read-only guard on the stored connection (warning only)'
}
elseif ($null -eq $check) {
    Step 'connection' 'WARNING service-check could not run - check it later with: service-check'
}
elseif ($null -eq $check.connection.ok) {
    Step 'connection' ('{0}: {1}' -f $check.connection.source, ($check.connection.lines -join ' '))
}
elseif ($check.connection.ok) {
    Step 'connection' ('{0}: read-only login confirmed' -f $check.connection.source)
}
else {
    Step 'connection' ('WARNING ' + ($check.connection.lines -join ' ') +
        ' - fix the login in the admin panel (Database connections)')
}

# ------------------------------------------------------------------ [winsw]
if ($script:WhatIf) {
    StepWhat 'winsw' ('would verify ' + $WinSwExe + ' against the pinned SHA-256 and download ' +
        $WinSwUrl + ' when it is missing')
}
elseif (-not $WinSwSha256) {
    Stop 'winsw' ('fill in WinSwSha256 from the official release page - nothing was installed')
}
else {
    if (-not (Test-Path $WinSwExe)) {
        Step 'winsw' ('downloading ' + $WinSwUrl)
        Invoke-WebRequest -Uri $WinSwUrl -OutFile $WinSwExe -UseBasicParsing
    }
    $hash = (Get-FileHash -Algorithm SHA256 -Path $WinSwExe).Hash
    if ($hash -ne $WinSwSha256) {
        Stop 'winsw' ('SHA-256 of ' + $WinSwExe + ' is ' + $hash + ', not the pinned ' +
            $WinSwSha256 + ' - nothing was installed')
    }
    Step 'winsw' ('WinSW ' + $WinSwVersion + ' verified')
}

# ------------------------------------------------------------------ [home]
$homeFolders = @($DataHome, (Join-Path $DataHome 'data'), (Join-Path $DataHome 'logs'), $SecretsDir,
    (Join-Path $DataHome 'index'))
if ($script:WhatIf) {
    StepWhat 'home' ('would create ' + ($homeFolders -join ', ') + ' and set their ACLs for ' +
        $ServiceAccount)
}
else {
    foreach ($folder in $homeFolders) {
        New-Item -ItemType Directory -Force -Path $folder | Out-Null
    }
    $acls = @(
        @($DataHome, @('/grant', ('{0}:(OI)(CI)F' -f $Administrators),
                   ('{0}:(OI)(CI)M' -f $ServiceAccount))),
        # The secrets folder is the one place that holds model keys: nothing but the
        # administrators and the service account may read it (R8-21).
        @($SecretsDir, @('/inheritance:r', '/grant', ('{0}:(OI)(CI)F' -f $Administrators),
                         ('{0}:(OI)(CI)M' -f $ServiceAccount))),
        @($Repo, @('/grant', ('{0}:(OI)(CI)RX' -f $ServiceAccount)))
    )
    foreach ($acl in $acls) {
        $out = & icacls $acl[0] $acl[1] 2>$null
        if ($LASTEXITCODE -ne 0) {
            Stop 'home' ('icacls failed for ' + $acl[0] + ': ' + ($out -join ' '))
        }
    }
    Step 'home' ($DataHome + ' ready: ' + $ServiceAccount + ' Modify, ' + $Administrators +
        ' Full; secrets and the repository read-only for everyone else')
}

# ------------------------------------------------------------------ [appdb] [index]
# ASSUMPTION: -CopyAppDb is the single offer - it brings the development app database and the
# already built index of the dataset over, because both are "work done once in the dev folder".
$repoDb = Join-Path $Repo 'data\bilgin.db'
$repoIndex = Join-Path $Repo ("index\{0}" -f $Dataset)
$homeIndex = Join-Path $DataHome ("index\{0}" -f $Dataset)
if ($script:WhatIf) {
    StepWhat 'appdb' ('with -CopyAppDb, would copy ' + $repoDb + ' to ' + $AppDb + ' when HOME has none')
}
elseif (-not $CopyAppDb) {
    Step 'appdb' 'skipped - pass -CopyAppDb to bring the development app database over'
}
elseif (Test-Path $AppDb) {
    Step 'appdb' ($AppDb + ' already exists - left alone')
}
elseif (-not (Test-Path $repoDb)) {
    Step 'appdb' ('no development app database at ' + $repoDb + ' - the first admin is created below')
}
else {
    Copy-Item -Path $repoDb -Destination $AppDb
    Step 'appdb' ('copied the development app database to ' + $AppDb)
}

if ($script:WhatIf) {
    StepWhat 'index' ('with -CopyAppDb, would copy ' + $repoIndex + ' to ' + $homeIndex + ' when missing')
}
elseif (-not $CopyAppDb) {
    Step 'index' 'skipped with -CopyAppDb left out'
}
elseif (Test-Path $homeIndex) {
    Step 'index' ($homeIndex + ' already exists - left alone')
}
elseif (-not (Test-Path $repoIndex)) {
    Step 'index' ('no built index for ' + $Dataset + ' in the repository - build it when needed')
}
else {
    Copy-Item -Path $repoIndex -Destination (Join-Path $DataHome 'index') -Recurse
    Step 'index' ('copied the index of ' + $Dataset + ' to ' + $homeIndex)
}

# ------------------------------------------------------------------ [secrets]
# A Windows service has no environment to set a model key in (R8-21): the key becomes a
# machine-scope DPAPI blob named after the variable, with the variable's name as its entropy.
# ASSUMPTION: the profile the service will run is the one the environment names, and 'strata' is
# the default the program itself falls back to (config.DEFAULT_LLM_MODEL).
$profileName = if ($env:NL2SQL_LLM_MODEL) { $env:NL2SQL_LLM_MODEL } else { 'strata' }
$keyEnv = ''
$modelsPath = Join-Path $Repo 'config\models.json'
if (Test-Path $modelsPath) {
    $entry = (Get-Content -Path $modelsPath -Raw | ConvertFrom-Json).profiles.PSObject.Properties[$profileName]
    if ($entry) { $keyEnv = [string]$entry.Value.api_key_env }
}
$secretFile = Join-Path $SecretsDir ($keyEnv + '.bin')
if ($script:WhatIf) {
    StepWhat 'secrets' ('would seal the model key of profile ' + $profileName + ' into ' +
        $SecretsDir + ' when the profile needs one')
}
elseif (-not $keyEnv) {
    Step 'secrets' ('the model profile ' + $profileName + ' needs no API key')
}
elseif (Test-Path $secretFile) {
    Step 'secrets' ($keyEnv + ' is already stored - left alone')
}
else {
    try { Add-Type -AssemblyName System.Security } catch { }
    $secure = Read-Host -AsSecureString ('Model API key for ' + $keyEnv + ' (profile ' + $profileName + ')')
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
        $blob = [Security.Cryptography.ProtectedData]::Protect(
            [Text.Encoding]::UTF8.GetBytes($plain),
            [Text.Encoding]::UTF8.GetBytes('bilgin-secret:' + $keyEnv),
            [Security.Cryptography.DataProtectionScope]::LocalMachine)
        [IO.File]::WriteAllBytes($secretFile, $blob)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
    Step 'secrets' ($keyEnv + ' sealed to ' + $secretFile)
}

# ------------------------------------------------------------------ [admin-user]
$adminProbe = "import sys; from nl2sql.auth.store import UserStore; " +
    "print(any(u['role'] == 'admin' for u in UserStore(sys.argv[1]).list_users()))"
if ($script:WhatIf) {
    StepWhat 'admin-user' ('would create the first administrator with: user add --role admin, ' +
        'when ' + $AppDb + ' has none')
}
else {
    if ((& $PythonExe -c $adminProbe $AppDb) -match 'True') {
        Step 'admin-user' 'the app database already has an administrator'
    }
    else {
        $name = Read-Host 'First administrator (username)'
        & $PythonExe -m nl2sql user add $name --role admin --lang $Lang
        if ($LASTEXITCODE -ne 0) {
            Stop 'admin-user' 'the administrator could not be created - the service would not start'
        }
        Step 'admin-user' ('administrator ' + $name + ' created')
    }
}

# ------------------------------------------------------------------ [xml]
if ($script:WhatIf) {
    StepWhat 'xml' ('would write ' + $ServiceXml + ' with the program itself; it is printed below')
    Write-Output (& $PythonExe -m nl2sql service-xml --port $Port --dataset $Dataset --home $DataHome --lang $Lang | Out-String)
}
else {
    & $PythonExe -m nl2sql service-xml --port $Port --dataset $Dataset --home $DataHome --lang $Lang --out $ServiceXml |
        Out-Null
    if ($LASTEXITCODE -ne 0) {
        Stop 'xml' 'the service XML could not be generated'
    }
    Step 'xml' ('written ' + $ServiceXml)
}

# ------------------------------------------------------------------ [install]
if ($script:WhatIf) {
    StepWhat 'install' ('would copy ' + $WinSwExe + ' to ' + $ServiceExe + ' and run: install')
}
else {
    Copy-Item -Path $WinSwExe -Destination $ServiceExe -Force
    & $ServiceExe install | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Stop 'install' ('the service could not be installed (exit code ' + $LASTEXITCODE + ')')
    }
    Step 'install' ('service ' + $ServiceName + ' installed')
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

# ------------------------------------------------------------------ [url]
Step 'url' $HealthUrl
exit 0
