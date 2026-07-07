"""Load ArduPilot dataflash (.bin/.log) and telemetry (.tlog) logs into per-message-type tables."""
from __future__ import annotations

import gc
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
from pymavlink import mavutil

# Max records collected per message type during parsing (prevents multi-GB Python lists).
_MAX_COLLECT = 200_000
# Target records per type stored as numpy arrays (subsampled from collected data).
_MAX_ROWS = 50_000

# Message types treated as "events" rather than time-series data.
EVENT_MSG_TYPES = {"ERR", "EV", "MSG", "MODE"}
# (msg_type, name_field, value_field) pairs holding parameter snapshots.
PARAM_SOURCES = [("PARM", "Name", "Value"), ("PARAM_VALUE", "param_id", "param_value")]
# Message types holding mission/waypoint definitions.
MISSION_MSG_TYPES = ["CMD", "MISSION_ITEM_INT", "MISSION_ITEM"]


@dataclass
class LogData:
    path: Path
    # message type -> {field_name: np.ndarray}, always includes "timestamp" (epoch seconds)
    messages: dict[str, dict[str, np.ndarray]] = field(default_factory=dict)
    start_time: float = 0.0
    end_time: float = 0.0

    @property
    def message_types(self) -> list[str]:
        return sorted(self.messages.keys())

    def fields_for(self, msg_type: str) -> list[str]:
        return [
            f for f, v in self.messages.get(msg_type, {}).items()
            if f != "timestamp" and np.issubdtype(v.dtype, np.number)
        ]

    def series(self, msg_type: str, field_name: str) -> tuple[np.ndarray, np.ndarray]:
        table = self.messages[msg_type]
        return table["timestamp"], table[field_name]

    def events(self) -> list[dict]:
        rows = []
        for msg_type in EVENT_MSG_TYPES:
            table = self.messages.get(msg_type)
            if not table:
                continue
            n = len(table["timestamp"])
            for i in range(n):
                row = {"type": msg_type, "timestamp": table["timestamp"][i]}
                for fname, values in table.items():
                    if fname == "timestamp":
                        continue
                    row[fname] = values[i]
                rows.append(row)
        rows.sort(key=lambda r: r["timestamp"])
        return rows

    def parameters(self) -> list[dict]:
        latest: dict[str, dict] = {}
        for msg_type, name_field, value_field in PARAM_SOURCES:
            table = self.messages.get(msg_type)
            if not table or name_field not in table or value_field not in table:
                continue
            names = table[name_field]
            values = table[value_field]
            times = table["timestamp"]
            for i in range(len(names)):
                name = names[i]
                if isinstance(name, bytes):
                    name = name.decode(errors="replace")
                name = str(name).rstrip("\x00").strip()
                if not name:
                    continue
                latest[name] = {"name": name, "value": float(values[i]), "timestamp": times[i]}
        return sorted(latest.values(), key=lambda r: r["name"])

    def mission(self) -> list[dict]:
        rows = []
        for msg_type in MISSION_MSG_TYPES:
            table = self.messages.get(msg_type)
            if not table:
                continue
            n = len(table["timestamp"])
            for i in range(n):
                row = {"type": msg_type, "timestamp": table["timestamp"][i]}
                for fname, values in table.items():
                    if fname == "timestamp":
                        continue
                    row[fname] = values[i]
                rows.append(row)
            break  # use the first mission source found
        return rows


def load_log(path: str | Path, progress_callback: Callable[[int], None] | None = None) -> LogData:
    path = Path(path)

    last_pct = -1

    def _progress(pct: float):
        nonlocal last_pct
        ipct = int(pct)
        if progress_callback is not None and ipct != last_pct:
            last_pct = ipct
            progress_callback(ipct)

    conn = mavutil.mavlink_connection(
        str(path), dialect="ardupilotmega",
        progress_callback=_progress if progress_callback else None,
    )

    raw: dict[str, dict[str, list]] = {}
    min_t = None
    max_t = None

    # Per-type state for doubling-reservoir adaptive subsampling.
    # Ensures uniform coverage of the full flight even for high-frequency types.
    _step: dict[str, int] = {}     # current keep-1-in-N step
    _counter: dict[str, int] = {}  # total messages seen per type

    while True:
        msg = conn.recv_match(blocking=False)
        if msg is None:
            break
        msg_type = msg.get_type()
        if msg_type in ("BAD_DATA", "UNKNOWN_92"):
            continue
        if progress_callback is not None:
            pct = getattr(conn, "percent", None)
            if pct is not None:
                _progress(pct)
        ts = getattr(msg, "_timestamp", None)
        if ts is None:
            continue

        # Always track full time range regardless of sampling decision
        if min_t is None or ts < min_t:
            min_t = ts
        if max_t is None or ts > max_t:
            max_t = ts

        # Adaptive uniform subsampling: skip if not on current step boundary
        cnt = _counter.get(msg_type, 0) + 1
        _counter[msg_type] = cnt
        step = _step.get(msg_type, 1)
        if cnt % step != 0:
            continue

        data = msg.to_dict()
        data.pop("mavpackettype", None)

        table = raw.setdefault(msg_type, {"timestamp": []})
        curr_n = len(table["timestamp"])

        if curr_n >= _MAX_COLLECT:
            # Stored too many — thin by 2× and double the step so future
            # messages arrive at half the rate, keeping uniform coverage.
            new_step = step * 2
            _step[msg_type] = new_step
            _counter[msg_type] = 0
            for k in list(table.keys()):
                table[k] = table[k][::2]

        table["timestamp"].append(ts)
        for k, v in data.items():
            if isinstance(v, (list, tuple)):
                continue  # skip array fields
            table.setdefault(k, []).append(v)

    if progress_callback is not None:
        progress_callback(100)

    messages: dict[str, dict[str, np.ndarray]] = {}
    for msg_type in list(raw.keys()):
        table = raw.pop(msg_type)   # release from raw so GC can reclaim memory type by type
        n = len(table["timestamp"])
        if n > _MAX_ROWS:
            step = max(1, n // _MAX_ROWS)
            sub = {k: v[::step] for k, v in table.items()}
            del table
            gc.collect()            # free large Python lists before numpy allocation
            table = sub
            n = len(table["timestamp"])
        converted = {}
        for k, v in table.items():
            if len(v) != n:
                continue
            try:
                converted[k] = np.asarray(v, dtype=float)
            except (TypeError, ValueError):
                converted[k] = np.asarray(v, dtype=object)
        del table
        messages[msg_type] = converted

    return LogData(
        path=path,
        messages=messages,
        start_time=min_t or 0.0,
        end_time=max_t or 0.0,
    )
