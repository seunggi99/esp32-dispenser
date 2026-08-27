import json
import logging
import os
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

import db
import result_bus

logger = logging.getLogger("mqtt_client")

MQTT_HOST = os.environ.get("MQTT_HOST", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))

TELEMETRY_TOPIC = "device/+/telemetry"
RESULT_TOPIC = "device/+/result"
COMMAND_TOPIC_TEMPLATE = "device/{device_id}/command"


def _topic_device_id(topic: str) -> str:
    return topic.split("/")[1]


def _on_connect(client, userdata, flags, reason_code, properties=None):
    logger.info("connected to mqtt broker at %s:%s rc=%s", MQTT_HOST, MQTT_PORT, reason_code)
    client.subscribe(TELEMETRY_TOPIC)
    client.subscribe(RESULT_TOPIC)


def _on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
    except (UnicodeDecodeError, json.JSONDecodeError):
        logger.warning("bad payload on %s: %r", msg.topic, msg.payload)
        return

    device_id = _topic_device_id(msg.topic)

    if msg.topic.endswith("/telemetry"):
        weight_g = payload.get("weight_g")
        if weight_g is None:
            logger.warning("telemetry payload missing weight_g: %r", payload)
            return
        db.insert_telemetry(
            device_id=device_id,
            weight_g=weight_g,
            received_at=datetime.now(timezone.utc).isoformat(),
        )
    elif msg.topic.endswith("/result"):
        command_id = payload.get("command_id")
        reported = payload.get("reported")
        if command_id is None or reported is None:
            logger.warning("result payload missing command_id/reported: %r", payload)
            return
        if not db.update_device_reported(command_id, reported):
            logger.warning("result for unknown command_id=%s device=%s", command_id, device_id)
        result_bus.notify_result(command_id, reported)


def create_client() -> mqtt.Client:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = _on_connect
    client.on_message = _on_message
    client.connect(MQTT_HOST, MQTT_PORT)
    return client


def publish_command(client: mqtt.Client, device_id: str, duration_ms: int, command_id: int) -> None:
    topic = COMMAND_TOPIC_TEMPLATE.format(device_id=device_id)
    payload = json.dumps({"command_id": command_id, "duration_ms": duration_ms})
    client.publish(topic, payload)
