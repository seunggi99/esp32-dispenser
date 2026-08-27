import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
import db
import mqtt_client
import result_bus
import verifier

CONNECTED_THRESHOLD_S = 5.0
SSE_INTERVAL_S = 1.0

logging.basicConfig(level=logging.INFO)


class CommandRequest(BaseModel):
    device_id: str
    duration_ms: int


class ConfigUpdate(BaseModel):
    expected_delta_min_g: Optional[float] = None
    expected_delta_max_g: Optional[float] = None
    stabilization_delay_s: Optional[float] = None
    result_wait_s: Optional[float] = None
    max_consecutive_failures: Optional[int] = None
    trust_device_report: Optional[bool] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    result_bus.bind_loop(asyncio.get_running_loop())
    client = mqtt_client.create_client()
    client.loop_start()
    app.state.mqtt_client = client
    yield
    client.loop_stop()
    client.disconnect()


app = FastAPI(lifespan=lifespan)


@app.post("/commands")
async def create_command(req: CommandRequest):
    try:
        return await verifier.execute_and_verify(app.state.mqtt_client, req.device_id, req.duration_ms)
    except verifier.DeviceHalted as e:
        raise HTTPException(status_code=409, detail=str(e))
    except verifier.NoWeightBaseline as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/devices/{device_id}/resume")
def resume_device(device_id: str):
    db.clear_halt(device_id)
    return {"device_id": device_id, "halted": False}


@app.get("/config")
def get_config():
    return {
        "trust_device_report": config.settings.trust_device_report,
        "expected_delta_min_g": config.settings.expected_delta_min_g,
        "expected_delta_max_g": config.settings.expected_delta_max_g,
        "stabilization_delay_s": config.settings.stabilization_delay_s,
        "result_wait_s": config.settings.result_wait_s,
        "max_consecutive_failures": config.settings.max_consecutive_failures,
    }


@app.post("/config")
def update_config(req: ConfigUpdate):
    for key, value in req.model_dump(exclude_none=True).items():
        setattr(config.settings, key, value)
    return get_config()


def _weight_pass(weight_before, weight_after) -> Optional[bool]:
    if weight_before is None or weight_after is None:
        return None
    delta = weight_after - weight_before
    return config.settings.expected_delta_min_g <= delta <= config.settings.expected_delta_max_g


def _build_snapshot() -> dict:
    telemetry = {row["device_id"]: row for row in db.list_latest_telemetry()}
    states = {row["device_id"]: row for row in db.list_device_states()}
    now = datetime.now(timezone.utc)

    devices = {}
    for device_id in set(telemetry) | set(states):
        t = telemetry.get(device_id)
        s = states.get(device_id)
        connected = False
        if t is not None:
            received_at = datetime.fromisoformat(t["received_at"])
            connected = (now - received_at).total_seconds() < CONNECTED_THRESHOLD_S
        devices[device_id] = {
            "weight_g": t["weight_g"] if t else None,
            "received_at": t["received_at"] if t else None,
            "connected": connected,
            "halted": bool(s["halted"]) if s else False,
            "halted_at": s["halted_at"] if s else None,
        }

    commands = []
    for row in db.list_recent_commands(20):
        weight_pass = _weight_pass(row["weight_before"], row["weight_after"])
        mismatch = row["device_reported"] == "done" and weight_pass is False
        commands.append({**row, "weight_pass": weight_pass, "mismatch": mismatch})

    return {
        "devices": devices,
        "commands": commands,
        "config": {
            "expected_delta_min_g": config.settings.expected_delta_min_g,
            "expected_delta_max_g": config.settings.expected_delta_max_g,
            "trust_device_report": config.settings.trust_device_report,
        },
    }


@app.get("/events")
async def events():
    async def gen():
        while True:
            yield f"data: {json.dumps(_build_snapshot())}\n\n"
            await asyncio.sleep(SSE_INTERVAL_S)

    return StreamingResponse(gen(), media_type="text/event-stream")


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
