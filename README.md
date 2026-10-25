# chilgok-bus-eta

칠곡군 동명면(학명리↔동명면) 버스 실시간 도착 안내. 공식 시간표가 없는 농어촌
노선의 실제 도착 패턴을 TAGO 공식 API로 모아 통계 시간표 + 실시간 도착 버튼을
제공하는 PWA.

설계: docs는 별도(원 설계/계획은 작업 리포 traffic-cctv-lab의
docs/superpowers/specs, docs/superpowers/plans 참고).

## 페이지

https://dyson-git.github.io/chilgok-bus-eta/ (GitHub Pages, `main` 루트에서 서빙)

## 데이터 수집

GitHub Actions(`.github/workflows/poll.yml`)가 5분마다 `python -m collector.poll`을
실행한다. 수집은 06:00–22:00 KST에만 동작하고 그 외 시간에는 아무 것도 하지 않는다.
결과는 `data/`에 저장되어 `main`에 자동 커밋된다. 저장소 시크릿 `TAGO_SERVICE_KEY`
(TAGO 공공데이터 서비스키)가 필요하다.

## 클라우드 수집 (지금 쓰는 방식)

Cloudflare Worker cron 이 06:00–22:00 KST 5분마다 TAGO 도착정보를 KV 에 쌓고(7일 보관),
`.github/workflows/import.yml`(`python -m collector.cloud_import`)이 가져와 `data/`에 기록·커밋한다.
이 저장소에서는 GitHub 예약 실행(schedule)이 돌지 않아서, PC 작업 스케줄러 "chilgok-bus-eta import"가
매시 10분(06:10–23:10) `scripts/trigger_import.ps1`로 이 작업을 실행시킨다(로그 `%LOCALAPPDATA%\chilgok-bus-eta\import.log`).
PC 가 꺼져 있던 시간은 다음 실행 때 채워진다. 아래 로컬 수집 작업("chilgok-bus-eta poll")은 꺼 두었다(data 커밋 충돌).

## 로컬 수집 (작업 스케줄러)

정기 수집은 로컬 PC의 Windows 작업 스케줄러가 5분마다 `scripts/local_poll.ps1`을
실행해 수행한다(pull → 수집 → `data/` 커밋 → `main`에 push). 서비스키는 `TAGO_SERVICE_KEY`
환경변수(사용자 범위)에서 읽는다. 로그는 `%LOCALAPPDATA%\chilgok-bus-eta\poll.log`.
GitHub Actions 워크플로는 수동 실행(`workflow_dispatch`) 백업용이다.

## 실시간 조회 (live-config.js)

페이지는 새로고침마다 TAGO를 직접 조회한다(CORS 허용). 설정은 `live-config.js`에 있으며
**서비스키가 공개 저장소에 포함된다**(사용자 결정). `collector/config.py`나 키가 바뀌면
`python scripts/gen_live_config.py`를 다시 실행한다. 전부 실패하면 `data/latest.json`으로 대체 표시한다.

## 테스트

```
pip install -r requirements.txt
python -m pytest -q
```
