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
실행한다. 수집은 06:00–21:30 KST에만 동작하고 그 외 시간에는 아무 것도 하지 않는다.
결과는 `data/`에 저장되어 `main`에 자동 커밋된다. 저장소 시크릿 `TAGO_SERVICE_KEY`
(TAGO 공공데이터 서비스키)가 필요하다.

## 테스트

```
pip install -r requirements.txt
python -m pytest -q
```
