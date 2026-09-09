param([switch]$InstallStartup, [switch]$Research, [switch]$Releases)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskUv = (Get-Command uv.exe).Source
$taskPaths = & $taskUv run --frozen --project $taskRoot zeus --repository $taskRoot paths | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Cannot resolve Zeus configuration' }
$taskRuntime = $taskPaths.runtime
New-Item -ItemType Directory -Force -Path $taskRuntime | Out-Null
$taskLaunchLock = $null
try {
    $taskLaunchLock = [IO.File]::Open((Join-Path $taskRuntime 'supervisor-launch.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    $taskPidFile = Join-Path $taskRuntime 'supervisor.pid'
    $taskExisting = $null
    if (Test-Path -LiteralPath $taskPidFile) {
        $taskExistingId = 0
        if ([int]::TryParse((Get-Content -LiteralPath $taskPidFile -Raw).Trim(), [ref]$taskExistingId)) {
            $taskExisting = Get-CimInstance Win32_Process -Filter "ProcessId=$taskExistingId" |
                Where-Object { $_.CommandLine -match '(zeus-supervisor|harness-supervisor|supervise\.py)' -and
                               $_.CommandLine -match [regex]::Escape($taskRoot) }
        }
    }
    if (-not $taskExisting) {
        $taskArguments = 'run --frozen --project "' + $taskRoot + '" zeus-supervisor --repository "' + $taskRoot + '"'
        if ($Research) { $taskArguments += ' --research' }
        if ($Releases) { $taskArguments += ' --releases' }
        $taskProcess = Start-Process -FilePath $taskUv -ArgumentList $taskArguments -WorkingDirectory $taskRoot `
            -RedirectStandardOutput (Join-Path $taskRuntime 'supervisor.log') `
            -RedirectStandardError (Join-Path $taskRuntime 'supervisor.err') -WindowStyle Hidden -PassThru
        $taskProcess.Id | Set-Content -LiteralPath $taskPidFile
        Write-Output ('Zeus supervisor started: ' + $taskProcess.Id)
    } else { Write-Output ('Zeus supervisor already running: ' + $taskExisting.ProcessId) }
    if ($InstallStartup) {
        $taskStartup = 'powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $PSCommandPath + '"'
        if ($Research) { $taskStartup += ' -Research' }
        if ($Releases) { $taskStartup += ' -Releases' }
        $taskRunKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
        New-ItemProperty -Path $taskRunKey -Name 'ZeusSupervisor' -Value $taskStartup -PropertyType String -Force | Out-Null
        Remove-ItemProperty -Path $taskRunKey -Name 'CodexHarnessSupervisor' -ErrorAction SilentlyContinue
    }
} finally {
    if ($taskLaunchLock) { $taskLaunchLock.Dispose() }
}
