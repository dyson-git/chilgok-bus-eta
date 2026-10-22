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

    # 이전 실행이 rebase 도중 멈췄다면 중단시켜 깨끗한 상태로 시작한다 (data/ 만 쓰므로 안전).
    $gitDir = (& git rev-parse --git-dir)
    if ((Test-Path (Join-Path $gitDir "rebase-merge")) -or (Test-Path (Join-Path $gitDir "rebase-apply"))) {
        $rc = Invoke-Native { git rebase --abort }
        Write-Log "WARN: stale rebase aborted (exit $rc)"
    }
    $others = @(& git status --porcelain | Where-Object { $_ -and ($_ -notmatch '^.. "?data/') })
    if ($others.Count -gt 0) { Write-Log ("WARN: non-data changes present: " + $others.Count + " (continuing)") }

    # 이전 실행에서 커밋/푸시 못 한 data/ 변경(jsonl 추가분)이 있으면 먼저 로컬 커밋한다.
    # 커밋된 내용은 rebase --abort 로도 사라지지 않고, 더티 트리 때문에 pull --rebase 가 거부되는 일도 없다.
    function Save-Data([string]$label) {
        if (-not (Test-Path "data")) { return 0 }
        $c = & git status --porcelain data
        if ([string]::IsNullOrWhiteSpace(($c | Out-String))) { return 0 }
        $kst = [DateTime]::UtcNow.AddHours(9).ToString("yyyy-MM-ddTHH:mm")
        $r = Invoke-Native { git add data }
        if ($r -ne 0) { return $r }
        return (Invoke-Native { git -c user.name=chilgok-poller -c user.email=noreply@localhost commit -m "data: $label $kst" })
    }
    function Sync-Main {
        $r = Invoke-Native { git pull --rebase --quiet origin main }
        if ($r -ne 0) { [void](Invoke-Native { git rebase --abort }) }
        return $r
    }

    $rc = Save-Data "recover"
    if ($rc -ne 0) { Write-Log "FAIL: git commit leftover (exit $rc)"; exit 1 }
    $rc = Sync-Main
    if ($rc -ne 0) { Write-Log "FAIL: git pull (exit $rc), rebase aborted"; exit 1 }

    $rc = Invoke-Native { python -m collector.poll }
    if ($rc -ne 0) { Write-Log "FAIL: collector.poll (exit $rc)"; exit 1 }

    $kst = [DateTime]::UtcNow.AddHours(9).ToString("yyyy-MM-ddTHH:mm")
    $rc = Save-Data "poll"
    if ($rc -ne 0) { Write-Log "FAIL: git commit (exit $rc)"; exit 1 }

    # 로컬에 아직 안 올라간 커밋이 없으면 할 일 없음
    $ahead = (& git rev-list --count "origin/main..HEAD")
    if ([int]$ahead -eq 0) { Write-Log "OK: no data change"; exit 0 }

    $rc = Invoke-Native { git push --quiet origin HEAD:main }
    if ($rc -ne 0) {
        $rc = Sync-Main
        if ($rc -ne 0) { Write-Log "FAIL: git pull after rejected push (exit $rc), rebase aborted"; exit 1 }
        $rc = Invoke-Native { git push --quiet origin HEAD:main }
        if ($rc -ne 0) { Write-Log "FAIL: git push (exit $rc)"; exit 1 }
        Write-Log "OK: pushed after retry ($ahead commit(s)) data: poll $kst"
        exit 0
    }
    Write-Log "OK: pushed ($ahead commit(s)) data: poll $kst"
    exit 0
} catch {
    Write-Log ("FAIL: " + $_.Exception.Message)
    exit 1
}
