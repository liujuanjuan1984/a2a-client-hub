#!/usr/bin/env python3

"""Stream formatter that converts Compass JSON logs into readable single-line output."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from typing import IO, Any, Dict

DEFAULT_COLUMNS = ("timestamp", "level", "app", "message", "request_id", "user_id")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Format PM2 JSON log stream into human-friendly lines."
    )
    parser.add_argument(
        "--columns",
        default=",".join(DEFAULT_COLUMNS),
        help="Comma-separated field names to display.",
    )
    parser.add_argument(
        "--time-format",
        default="%Y-%m-%d %H:%M:%S",
        help="strftime format string applied to ISO timestamps.",
    )
    return parser.parse_args()


def normalize_timestamp(value: Any, fmt: str) -> str:
    if not isinstance(value, str):
        return "-"
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return dt.strftime(fmt)


def sanitize(value: Any) -> str:
    if value is None:
        return "-"
    text = str(value)
    return " ".join(text.splitlines())


def extract_inner_record(payload: Dict[str, Any]) -> Dict[str, Any]:
    record: Dict[str, Any] = {}

    if "data" in payload and isinstance(payload["data"], str):
        data_str = payload["data"].strip()
        if data_str.startswith("{") and data_str.endswith("}"):
            try:
                inner = json.loads(data_str)
            except json.JSONDecodeError:
                pass
            else:
                record.update(inner)
        if not record:
            record["message"] = data_str
    else:
        record.update(payload)

    record.setdefault("timestamp", payload.get("timestamp"))
    record.setdefault("level", payload.get("type"))
    process = payload.get("process")
    if isinstance(process, dict):
        record.setdefault("app", process.get("name"))

    return record


def render_line(
    payload: Dict[str, Any], columns: tuple[str, ...], time_fmt: str
) -> str:
    record = extract_inner_record(payload)
    values: list[str] = []
    for key in columns:
        raw = record.get(key)
        if key == "timestamp":
            values.append(normalize_timestamp(raw, time_fmt))
        else:
            values.append(sanitize(raw))
    return " | ".join(values)


def process_stream(
    stream: IO[str], columns: tuple[str, ...], time_fmt: str
) -> None:
    for raw_line in stream:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError:
            print(raw_line, file=sys.stderr)
            continue
        print(render_line(payload, columns, time_fmt))
        sys.stdout.flush()


def main() -> None:
    args = parse_args()
    columns = tuple(part.strip() for part in args.columns.split(",") if part.strip())
    if not columns:
        columns = DEFAULT_COLUMNS
    process_stream(sys.stdin, columns, args.time_format)


if __name__ == "__main__":
    main()
