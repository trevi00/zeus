import os
import shutil
from pathlib import Path

import pytest

from codex_harness.adapters.commands import run_process


@pytest.mark.skipif(os.name != "nt", reason="Native PowerShell launcher behavior")
def test_launchers_handle_corrupt_pid_custom_paths_and_duplicate_start(tmp_path):
    root = tmp_path / "Zeus 한글 workspace"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    source = Path(__file__).resolve().parents[1] / "scripts"
    for name in ("start_supervisor.ps1", "start_monitor.ps1"):
        shutil.copy2(source / name, scripts / name)
    # No real uv/process/registry operations: the native shell exercises the actual launch scripts.
    (root / "fake-uv.ps1").write_text(
        "@{runtime=$global:fixtureRuntime} | ConvertTo-Json -Compress\n", encoding="utf-8-sig")
    driver = root / "test.ps1"
    driver.write_text(r'''
$ErrorActionPreference = 'Stop'
$global:LASTEXITCODE = 0
$global:fixtureRuntime = Join-Path $PSScriptRoot 'custom runtime'
$global:fixtureUv = Join-Path $PSScriptRoot 'fake-uv.ps1'
$global:fixtureProcesses = @()
$global:fixtureRegistry = @()
New-Item -ItemType Directory -Path $global:fixtureRuntime | Out-Null
foreach ($name in @('supervisor', 'monitor-web', 'monitor-collect')) {
    'broken PID' | Set-Content (Join-Path $global:fixtureRuntime ($name + '.pid'))
    'preserved log' | Set-Content (Join-Path $global:fixtureRuntime ($name + '.log'))
}
function Get-Command { param($Name) @{Source=$global:fixtureUv} }
function Get-CimInstance {
    param($ClassName, $Filter)
    $idValue = [int]($Filter -replace 'ProcessId=', '')
    $global:fixtureProcesses | Where-Object { $_.ProcessId -eq $idValue }
}
function Start-Process {
    param($FilePath, $ArgumentList, $WorkingDirectory, $RedirectStandardOutput,
          $RedirectStandardError, $WindowStyle, [switch]$PassThru)
    if ($WindowStyle -ne 'Hidden' -or $ArgumentList -notmatch '--frozen' -or
        $ArgumentList -notmatch '--repository') { throw 'Invalid startup options' }
    if (-not $RedirectStandardOutput.StartsWith($global:fixtureRuntime)) { throw 'Wrong runtime' }
    $idValue = 400 + $global:fixtureProcesses.Count
    $global:fixtureProcesses += [pscustomobject]@{ProcessId=$idValue; CommandLine=$ArgumentList}
    return [pscustomobject]@{Id=$idValue}
}
function New-ItemProperty { param($Path, $Name, $Value, $PropertyType, [switch]$Force)
    $global:fixtureRegistry += [pscustomobject]@{Name=$Name; Value=$Value}
}
function Remove-ItemProperty { param($Path, $Name, $ErrorAction) }
& (Join-Path $PSScriptRoot 'scripts/start_supervisor.ps1') -Research -Releases -InstallStartup
& (Join-Path $PSScriptRoot 'scripts/start_monitor.ps1') -InstallStartup
& (Join-Path $PSScriptRoot 'scripts/start_supervisor.ps1')
& (Join-Path $PSScriptRoot 'scripts/start_monitor.ps1')
if ($global:fixtureProcesses.Count -ne 3) { throw 'Duplicate process launched' }
if ($global:fixtureRegistry.Count -ne 2) { throw 'Unexpected startup registration' }
if ($global:fixtureRegistry[0].Value -notmatch '-Research -Releases') { throw 'Startup flags lost' }
foreach ($name in @('supervisor', 'monitor-web', 'monitor-collect')) {
    if ((Get-Content (Join-Path $global:fixtureRuntime ($name + '.log'))).Trim() -ne 'preserved log') {
        throw 'Existing log truncated'
    }
}
'launcher fixtures passed'
''', encoding="utf-8-sig")
    result = run_process(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(driver)])
    assert result.returncode == 0, result.stdout + result.stderr
    assert "launcher fixtures passed" in result.stdout
