import asyncio
import logging
import time
from datetime import datetime, timezone

import config
import db
import mqtt_client
import result_bus

logger = logging.getLogger("verifier")


class DeviceHalted(Exception):
    def __init__(self, device_id: str):
        super().__init__(f"device {device_id} is halted")
        self.device_id = device_id


class NoWeightBaseline(Exception):
    def __init__(self, device_id: str):
        super().__init__(f"no weight baseline for device {device_id}")
        self.device_id = device_id


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _weight_verdict(weight_before: float | None, weight_after: float | None) -> bool:
    if weight_before is None or weight_after is None:
        return False
    delta = weight_after - weight_before
    return config.settings.expected_delta_min_g <= delta <= config.settings.expected_delta_max_g


async def _measure_weight_at_deadline(device_id: str, deadline_delay: float, publish_at: float) -> float | None:
    remaining = deadline_delay - (time.monotonic() - publish_at)
    if remaining > 0:
        await asyncio.sleep(remaining)
    return db.get_latest_weight(device_id)


async def _await_result(future: asyncio.Future, command_id: int, timeout: float):
    try:
        reported = await asyncio.wait_for(future, timeout=timeout)
        return reported, False
    except asyncio.TimeoutError:
        result_bus.cancel_wait(command_id)
        return None, True


async def execute_and_verify(mqtt_conn, device_id: str, duration_ms: int) -> dict:
    if db.is_halted(device_id):
        raise DeviceHalted(device_id)
    if db.get_latest_weight(device_id) is None:
        raise NoWeightBaseline(device_id)

    now = _now_iso()
    command_id = db.insert_command(
        device_id=device_id,
        duration_ms=duration_ms,
        issued_at=now,
        weight_before=None,
        created_at=now,
    )

    settings = config.settings
    attempt = 0
    weight_before = None
    weight_after = None
    result_timeout = False
    verdict = None

    while True:
        attempt += 1
        logger.info(
            "command %s attempt %d/%d for %s",
            command_id, attempt, settings.max_consecutive_failures, device_id,
        )

        # 1. 명령 직전 무게 스냅샷
        weight_before = db.get_latest_weight(device_id)

        # 2. command publish (재시도마다 같은 command_id 재사용)
        future = result_bus.wait_for_result(command_id)
        publish_at = time.monotonic()
        mqtt_client.publish_command(mqtt_conn, device_id, duration_ms, command_id)

        # 3. result 대기와 무게 재측정을 병렬로 진행한다.
        #    - result 대기: result_wait_s 동안만 (응답 여부 기록용, 판정에는 안 씀)
        #    - 무게 재측정: (발행 시각 + duration_ms + stabilization_delay_s) 시점에 고정
        #    result가 늦게 오거나 아예 안 와도 무게 측정 시점은 밀리지 않는다.
        deadline_delay = duration_ms / 1000.0 + settings.stabilization_delay_s
        weight_after, (reported, result_timeout) = await asyncio.gather(
            _measure_weight_at_deadline(device_id, deadline_delay, publish_at),
            _await_result(future, command_id, settings.result_wait_s),
        )

        # 4. delta가 기대범위 내인지 판정 (기록은 항상 하되, 대조군 모드에서는 판정에 쓰지 않는다)
        weight_passed = _weight_verdict(weight_before, weight_after)
        responded = not result_timeout

        if settings.trust_device_report:
            # 대조군 모드: 무게는 무시하고 "응답했다"는 사실만으로 판정한다.
            passed = responded
        else:
            passed = weight_passed

        if passed:
            verdict = "pass"
            db.update_command_result(command_id, weight_before, weight_after, verdict, attempt - 1, result_timeout)
            db.clear_halt(device_id)
            break

        if attempt >= settings.max_consecutive_failures:
            verdict = "fail"
            db.update_command_result(command_id, weight_before, weight_after, verdict, attempt - 1, result_timeout)
            db.set_halted(device_id, _now_iso())
            logger.warning("device %s HALTED after %d consecutive failures", device_id, attempt)
            break

        db.update_command_result(command_id, weight_before, weight_after, None, attempt, result_timeout)

    return {
        "id": command_id,
        "device_id": device_id,
        "duration_ms": duration_ms,
        "verdict": verdict,
        "retry_count": attempt - 1,
        "weight_before": weight_before,
        "weight_after": weight_after,
        "result_timeout": result_timeout,
        "device_reported": reported,
        "halted": verdict == "fail",
        "trust_device_report": settings.trust_device_report,
    }
