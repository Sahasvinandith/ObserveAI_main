"""
shared/stream_utils.py

Helpers for Redis Streams: publish, consume, and parse messages.
All services in the ObserveAI pipeline use these helpers so that
field-encoding conventions are applied consistently.
"""

import json
import time
import logging
import redis
from typing import Any, Optional


def xadd_json(
    r: redis.Redis,
    stream: str,
    data: dict,
    maxlen: int = 1000,
    approximate: bool = True,
) -> str:
    """
    Publish a dict to a Redis Stream.

    Nested values (lists, dicts) are JSON-serialised into the hash field.
    All values are sent as strings (Redis requirement for stream hash fields).

    Args:
        r:           Redis client.
        stream:      Stream key name.
        data:        Dict of fields to publish. Values are str-coerced.
        maxlen:      Approximate MAXLEN trim applied at write time.
        approximate: Use ~ trimming (True) or exact (False).

    Returns:
        The Redis Stream message ID of the added entry.
    """
    encoded: dict[str, str] = {}
    for k, v in data.items():
        if isinstance(v, (list, dict)):
            encoded[k] = json.dumps(v)
        else:
            encoded[k] = str(v)

    return r.xadd(stream, encoded, maxlen=maxlen, approximate=approximate)


def xreadgroup_json(
    r: redis.Redis,
    group: str,
    consumer: str,
    streams: dict[str, str],
    count: int = 10,
    block_ms: int = 100,
) -> list[tuple[str, list[tuple[str, dict]]]]:
    """
    Wrapper around XREADGROUP that returns decoded message dicts.

    Args:
        r:         Redis client.
        group:     Consumer group name.
        consumer:  Consumer name within the group.
        streams:   Dict of {stream_key: last_id}. Use ">" for new messages.
        count:     Maximum messages to fetch per call.
        block_ms:  Milliseconds to block waiting for messages.

    Returns:
        Same structure as redis-py xreadgroup: list of (stream, [(msg_id, fields), ...])
        but fields are already decoded (decode_responses=True on the client).
    """
    result = r.xreadgroup(
        groupname=group,
        consumername=consumer,
        streams=streams,
        count=count,
        block=block_ms,
    )
    return result or []


def parse_message(fields: dict) -> dict:
    """
    Attempt JSON parsing on any field whose value looks like a JSON array or object.
    Leaves non-JSON fields as strings.

    This is intentionally lenient: if a field cannot be parsed as JSON it stays as-is.
    """
    parsed = {}
    for k, v in fields.items():
        if isinstance(v, str) and (v.startswith("{") or v.startswith("[")):
            try:
                parsed[k] = json.loads(v)
            except (json.JSONDecodeError, ValueError):
                parsed[k] = v
        else:
            parsed[k] = v
    return parsed


def ensure_consumer_group(
    r: redis.Redis,
    stream: str,
    group: str,
    start_id: str = "$",
) -> None:
    """
    Create a consumer group if it does not already exist.
    Uses MKSTREAM so the stream is created if absent.

    Args:
        r:        Redis client.
        stream:   Stream key.
        group:    Consumer group name.
        start_id: Start ID for the group ("$" = only new messages, "0" = all).
    """
    try:
        r.xgroup_create(stream, group, id=start_id, mkstream=True)
    except redis.exceptions.ResponseError as exc:
        # BUSYGROUP means the group already exists — that is fine.
        if "BUSYGROUP" not in str(exc):
            raise


def publish_to_dlq(
    r: redis.Redis,
    original_stream: str,
    original_msg_id: str,
    original_fields: dict,
    error: Exception,
    consumer_name: str,
    group_name: str,
    retry_count: int = 1,
    maxlen: int = 1000,
) -> None:
    """
    Publish a failed message to the dead-letter queue for that stream.

    DLQ stream key convention: dlq::{original_stream}
    """
    dlq_stream = f"dlq::{original_stream}"
    payload = {
        "original_stream": original_stream,
        "original_msg_id": original_msg_id,
        "original_fields": json.dumps(original_fields),
        "error_class": type(error).__name__,
        "error_message": str(error),
        "retry_count": str(retry_count),
        "failed_at": f"{time.time():.3f}",
        "consumer_name": consumer_name,
        "group_name": group_name,
    }
    try:
        r.xadd(dlq_stream, payload, maxlen=maxlen, approximate=True)
    except Exception as dlq_err:
        logging.error("Failed to publish to DLQ %s: %s", dlq_stream, dlq_err)


def log_json(level: str, service: str, msg: str, **extra: Any) -> None:
    """
    Emit a JSON-structured log line to stdout.

    Args:
        level:   "info", "warning", "error", "debug"
        service: Service identifier string.
        msg:     Human-readable message.
        **extra: Additional key-value pairs appended to the log object.
    """
    record = {"level": level, "service": service, "msg": msg, "ts": f"{time.time():.3f}"}
    record.update({k: str(v) for k, v in extra.items()})
    print(json.dumps(record), flush=True)
