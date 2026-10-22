# 로컬 PC 작업 스케줄러용 수집 스크립트 (Windows PowerShell 5.1 호환, 5분 주기 실행)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$logDir = Join-Path $env:LOCALAPPDATA "chilgok-bus-eta"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir "poll.log"

function Write-Log([string]$msg) {
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-ddTHH:mm:ss"), $msg
    Add-Content -Path $logFile -Value $line -Encoding UTF8
    $all = @(Get-Content -Path $logFile -Encoding UTF8)
    if ($all.Count -gt 2000) {
        $all | Select-Object -Last 2000 | Set-Content -Path $logFile -Encoding UTF8
    }
}

# 네이티브 명령 실행: stderr 출력이 예외로 바뀌지 않게 하고 종료 코드만 반환
function Invoke-Native([scriptblock]$cmd) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $cmd *> $null } finally { $ErrorActionPreference = $prev }
    return $LASTEXITCODE
}

try {
    $key = $env:TAGO_SERVICE_KEY
    if ([string]::IsNullOrWhiteSpace($key)) {
        $key = [Environment]::GetEnvironmentVariable("TAGO_SERVICE_KEY", "User")
    }
    if ([string]::IsNullOrWhiteSpace($key)) {
        Write-Log "FAIL: TAGO_SERVICE_KEY not set"
        exit 1
    }
    $env:TAGO_SERVICE_KEY = $key.Trim()

    $rc = Invoke-Native { git pull --rebase --quiet origin main }
    if ($rc -ne 0) { Write-Log "FAIL: git pull (exit $rc)"; exit 1 }

    $rc = Invoke-Native { python -m collector.poll }
    if ($rc -ne 0) { Write-Log "FAIL: collector.poll (exit $rc)"; exit 1 }

    if (-not (Test-Path "data")) { Write-Log "OK: no data dir"; exit 0 }
    $changes = & git status --porcelain data
    if ([string]::IsNullOrWhiteSpace(($changes | Out-String))) { Write-Log "OK: no data change"; exit 0 }

    $kst = [DateTime]::UtcNow.AddHours(9).ToString("yyyy-MM-ddTHH:mm")
    $rc = Invoke-Native { git add data }
    if ($rc -ne 0) { Write-Log "FAIL: git add (exit $rc)"; exit 1 }
    $rc = Invoke-Native { git -c user.name=chilgok-poller -c user.email=noreply@localhost commit -m "data: poll $kst" }
    if ($rc -ne 0) { Write-Log "FAIL: git commit (exit $rc)"; exit 1 }

    $rc = Invoke-Native { git push --quiet origin HEAD:main }
    if ($rc -ne 0) {
        $rc = Invoke-Native { git pull --rebase --quiet origin main }
        if ($rc -ne 0) { Write-Log "FAIL: git pull after rejected push (exit $rc)"; exit 1 }
        $rc = Invoke-Native { git push --quiet origin HEAD:main }
        if ($rc -ne 0) { Write-Log "FAIL: git push (exit $rc)"; exit 1 }
        Write-Log "OK: committed and pushed (after retry) data: poll $kst"
        exit 0
    }
    Write-Log "OK: committed and pushed data: poll $kst"
    exit 0
} catch {
    Write-Log ("FAIL: " + $_.Exception.Message)
    exit 1
}
