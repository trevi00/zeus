param([switch]$InstallStartup)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskUv = (Get-Command uv.exe).Source
$taskPaths = & $taskUv run --frozen --project $taskRoot zeus --repository $taskRoot paths | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Cannot resolve Zeus configuration' }
$taskRuntime = $taskPaths.runtime
New-Item -ItemType Directory -Force -Path $taskRuntime | Out-Null
$taskLaunchLock = $null
try {
$taskLaunchLock = [IO.File]::Open((Join-Path $taskRuntime 'monitor-launch.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
foreach ($taskMode in @('collect', 'web')) {
    $taskPidFile = Join-Path $taskRuntime ('monitor-' + $taskMode + '.pid')
    $taskExisting = $null
    if (Test-Path -LiteralPath $taskPidFile) {
        $taskExistingId = 0
        if ([int]::TryParse((Get-Content -LiteralPath $taskPidFile -Raw).Trim(), [ref]$taskExistingId)) {
        $taskExisting = Get-CimInstance Win32_Process -Filter "ProcessId=$taskExistingId" |
            Where-Object { $_.CommandLine -match '(zeus-monitor|monitor\.py)' -and
                           $_.CommandLine -match [regex]::Escape($taskRoot) -and $_.CommandLine -like ('*' + $taskMode + '*') }
        }
    }
    if (-not $taskExisting) {
        $taskArguments = 'run --frozen --project "' + $taskRoot + '" zeus-monitor --repository "' + $taskRoot + '" ' + $taskMode
        $taskProcess = Start-Process -FilePath $taskUv -ArgumentList $taskArguments -WorkingDirectory $taskRoot `
            -RedirectStandardOutput (Join-Path $taskRuntime ('monitor-' + $taskMode + '.log')) `
            -RedirectStandardError (Join-Path $taskRuntime ('monitor-' + $taskMode + '.err')) -WindowStyle Hidden -PassThru
        $taskProcess.Id | Set-Content -LiteralPath $taskPidFile
    }
}
if ($InstallStartup) {
    $taskStartup = 'powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $PSCommandPath + '"'
    New-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name ZeusMonitor `
        -Value $taskStartup -PropertyType String -Force | Out-Null
    Remove-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name CodexHarnessMonitor -ErrorAction SilentlyContinue
}
Write-Output 'Zeus monitor: http://127.0.0.1:8787'

} finally {
    if ($taskLaunchLock) { $taskLaunchLock.Dispose() }
}
