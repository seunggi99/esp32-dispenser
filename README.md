# esp32-dispenser

ESP32 기반 무인 디스펜서. 장비의 자체 보고("명령 수행했다")를 신뢰하지 않고,
로드셀 무게 실측으로 서버가 직접 성공/실패를 판정하는 것이 이 프로젝트의 핵심 설계
원칙이다.

## 왜 무게로 판정하는가

장비는 "명령을 수행했다"는 사실만 보고할 뿐, 실제로 무언가 토출됐는지는 보고하지
않는다 (그리고 이 프로젝트에서는 장비가 성공/실패를 자체 판정해서 보고하는 구조를
허용하지 않는다). WiFi 재연결, 액추에이터 전원 차단 등으로 ESP32는 살아있지만 실제
동작은 실패하는 경우가 실제로 발생하며, `docs/experiments/`에 이를 같은 물리
조건에서 재현한 실험 결과가 있다.

## 구조

```
firmware/   ESP32 펌웨어 (PlatformIO). OLED 상태 표시, HX711 로드셀, MQTT 명령 수신/결과 보고
server/     FastAPI 서버. MQTT 구독/발행, SQLite 저장, 무게 기반 검증 엔진, SSE 대시보드
scripts/    trust/verify 모드 대조 실험 스크립트
docs/       트러블슈팅 기록, 실험 결과
```

## 동작 흐름

1. 서버가 `POST /commands`로 명령을 받으면 직전 무게를 스냅샷하고 `device/{id}/command`로 발행 (payload에 `command_id` 포함)
2. 장비는 펌프를 구동한 뒤 `device/{id}/result`로 같은 `command_id`를 그대로 echo하며 `"done"`만 보고 (성공/실패 판정 내용은 없음)
3. 서버는 (발행 시각 + `duration_ms` + `stabilization_delay_s`) 시점에 무게를 재측정하고, delta가 기대범위 안인지로만 판정한다. result는 "응답했다"는 사실만 기록하고 판정에는 쓰지 않는다
4. 판정 실패 시 재시도, 연속 3회 실패 시 해당 장비를 HALT (신규 명령 거부)
5. `TRUST_DEVICE_REPORT` 설정을 켜면 무게를 무시하고 장비 보고만으로 판정하는 대조군 모드로 전환 가능 (런타임 토글)

## 펌웨어

`firmware/src/secrets.h`를 직접 만들어야 한다 (git에는 없음):

```cpp
#pragma once
#define WIFI_SSID     "..."
#define WIFI_PASSWORD "..."
#define MQTT_HOST     "..."
#define MQTT_PORT     1883
#define DEVICE_ID     "dispenser-01"
```

```bash
cd firmware
pio run -t upload
```

## 서버

```bash
cd server
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn main:app --reload
```

로컬에 MQTT 브로커(예: mosquitto)가 `MQTT_HOST`/`MQTT_PORT` 환경변수(기본
`localhost:1883`)로 떠 있어야 한다.

### API

| 엔드포인트 | 설명 |
|---|---|
| `POST /commands` | `{device_id, duration_ms}` — 명령 발행 + 검증까지 끝내고 결과 반환. HALT 상태면 409 |
| `POST /devices/{device_id}/resume` | HALT 해제 |
| `GET /config` | 현재 검증 설정 조회 |
| `POST /config` | 보낸 필드만 부분 갱신 (예: `{"trust_device_report": true}`) |
| `GET /events` | SSE. 대시보드가 구독하는 실시간 스냅샷 |

### 대시보드

서버 실행 후 `http://localhost:8000/` — 장비별 현재 무게/연결 상태/HALT 여부와
최근 명령 20건(장비 보고 vs 무게 판정 대조)을 1초 간격으로 갱신해서 보여준다.
장비는 성공이라 보고했는데 무게 판정은 실패인 행은 강조 표시된다.

## 실험 스크립트

```bash
python3 scripts/experiment.py --device-id dispenser-01 --duration-ms 3000
```

trust/verify 모드를 각각 N회(기본 20회)씩 순차 실행하고 CSV로 저장, 마지막에
모드별 pass/fail·평균 delta·오판 건수를 표로 출력한다. 실행 중 HALT가 걸리면
자동으로 resume하고 계속 진행한다.

## 문서

- [`docs/troubleshooting.md`](docs/troubleshooting.md) — 개발 중 겪은 문제와 원인 정리
- [`docs/experiments/`](docs/experiments/) — trust vs verify 대조 실험 결과
