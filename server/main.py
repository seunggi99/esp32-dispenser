import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import config
import db
import mqtt_client
import result_bus
import verifier

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
