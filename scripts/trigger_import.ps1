# 작업 스케줄러용: GitHub 가져오기 작업(import.yml)을 매시 실행시킨다 (Windows PowerShell 5.1 호환)
# 이 저장소에서는 GitHub 예약 실행(schedule)이 한 번도 돌지 않았다 - 수동 실행(workflow_dispatch)만 된다.
# 기록·커밋은 GitHub 작업이 하므로 PC 는 누르기만 한다. 클라우드가 7일치를 보관하므로 PC 가 꺼졌던 시간도 다음 실행 때 채워진다.
$ErrorActionPreference = "Continue"

$logDir = Join-Path $env:LOCALAPPDATA "chilgok-bus-eta"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir "import.log"

$out = & gh workflow run import.yml -R dyson-git/chilgok-bus-eta 2>&1 | Out-String
$code = $LASTEXITCODE
$msg = if ($code -eq 0) { "OK: import triggered" } else { "ERROR: gh exit $code " + $out.Trim() }
Add-Content -Path $logFile -Value ("{0} {1}" -f (Get-Date -Format "yyyy-MM-ddTHH:mm:ss"), $msg) -Encoding UTF8
$all = @(Get-Content -Path $logFile -Encoding UTF8)
if ($all.Count -gt 500) { $all | Select-Object -Last 500 | Set-Content -Path $logFile -Encoding UTF8 }
exit $code
