"""Alarm management after the ISA-18.2 lifecycle.

Design rules applied:
  * Every alarm has a priority, setpoint, deadband, on-delay, consequence and operator action.
  * Only conditions that need an operator action are alarms; informational states stay on the display.
  * Chatter control: on-delay before raising, deadband before clearing.
  * Suppression by design: a child alarm is suppressed while its parent is active.
  * Lifecycle: active-unacknowledged -> active-acknowledged -> return-to-normal.
  * KPIs: alarm rate per 10 min, flood events, standing alarms, chattering alarms.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
FLOOD_LIMIT = 10          # alarms per 10 minutes (EEMUA 191 / ISA-18.2 guidance)
STANDING_AFTER_S = 24 * 3600


@dataclass(frozen=True)
class AlarmDef:
    type: str
    priority: str
    on_delay: int            # evaluation cycles the condition must hold before raising
    message: str
    consequence: str
    action: str


@dataclass
class Alarm:
    id: int
    tag: str
    type: str
    segment_id: int
    priority: str
    message: str
    consequence: str
    action: str
    state: str                # active_unack | active_ack | rtn_unack
    raised_ts: float
    value: float | None = None
    raised_value: float | None = None
    setpoint: str = ""
    ack_ts: float | None = None
    cleared_ts: float | None = None
    repeats: int = 0
    lat: float | None = None
    lon: float | None = None

    def to_dict(self) -> dict:
        return dict(self.__dict__)


class AlarmManager:
    def __init__(self, auto_archive_rtn_s: float | None = None):
        self.auto_archive_rtn_s = auto_archive_rtn_s
        self.active: dict[str, Alarm] = {}
        self._pending: dict[str, int] = {}
        self._next_id = 1
        self.raise_times: deque[float] = deque()
        self.total_raised = 0
        self.flood_events = 0
        self._in_flood = False
        self.history: deque[dict] = deque(maxlen=500)
        self.chatter: dict[str, int] = {}

    def _create(self, tag: str, adef: AlarmDef, seg: int, ts: float, value, setpoint: str, lat=None, lon=None) -> Alarm:
        a = Alarm(self._next_id, tag, adef.type, seg, adef.priority, adef.message, adef.consequence, adef.action,
                  "active_unack", ts, value, value, setpoint, lat=lat, lon=lon)
        self._next_id += 1
        self.active[tag] = a
        self.raise_times.append(ts)
        self.total_raised += 1
        return a

    def evaluate(self, tag: str, adef: AlarmDef, seg: int, ts: float, raise_cond: bool, clear_cond: bool,
                 value=None, setpoint: str = "", suppressed: bool = False):
        """Level alarm with on-delay and deadband (raise_cond/clear_cond differ by the deadband)."""
        a = self.active.get(tag)
        if suppressed:
            self._pending.pop(tag, None)
            if a is not None:
                self._return_to_normal(a, ts, suppressed=True)
            return
        if a is None:
            if raise_cond:
                n = self._pending.get(tag, 0) + 1
                if n >= adef.on_delay:
                    self._pending.pop(tag, None)
                    self._create(tag, adef, seg, ts, value, setpoint)
                else:
                    self._pending[tag] = n
            else:
                self._pending.pop(tag, None)
            return
        a.value = value
        if a.state == "rtn_unack" and raise_cond:
            a.state, a.repeats, a.cleared_ts = "active_unack", a.repeats + 1, None
            self.chatter[tag] = self.chatter.get(tag, 0) + 1
        elif a.state in ("active_unack", "active_ack") and clear_cond:
            self._return_to_normal(a, ts)

    def raise_event(self, tag: str, adef: AlarmDef, seg: int, ts: float, value=None, setpoint="", lat=None, lon=None):
        """Event alarm (e.g. pothole confirmed): raised once, cleared by an external action."""
        if tag not in self.active:
            self._create(tag, adef, seg, ts, value, setpoint, lat, lon)

    def clear_event(self, tag: str, ts: float):
        a = self.active.get(tag)
        if a is not None:
            self._return_to_normal(a, ts)

    def _return_to_normal(self, a: Alarm, ts: float, suppressed: bool = False):
        if a.state == "active_ack" or suppressed:
            self._archive(a, ts)
        elif a.state == "active_unack":
            a.state, a.cleared_ts = "rtn_unack", ts

    def _archive(self, a: Alarm, ts: float):
        a.cleared_ts = a.cleared_ts or ts
        self.history.append(a.to_dict())
        self.active.pop(a.tag, None)

    def housekeeping(self, ts: float):
        """Optional demo convenience: archive returned-to-normal alarms nobody acknowledged."""
        if self.auto_archive_rtn_s is None:
            return
        for a in list(self.active.values()):
            if a.state == "rtn_unack" and a.cleared_ts is not None and ts - a.cleared_ts > self.auto_archive_rtn_s:
                self._archive(a, ts)

    def acknowledge_all(self, ts: float) -> int:
        n = 0
        for a in list(self.active.values()):
            if self.acknowledge(a.id, ts):
                n += 1
        return n

    def acknowledge(self, alarm_id: int, ts: float) -> bool:
        for a in list(self.active.values()):
            if a.id == alarm_id:
                if a.state == "active_unack":
                    a.state, a.ack_ts = "active_ack", ts
                elif a.state == "rtn_unack":
                    a.ack_ts = ts
                    self._archive(a, ts)
                return True
        return False

    def kpis(self, ts: float) -> dict:
        while self.raise_times and ts - self.raise_times[0] > 600.0:
            self.raise_times.popleft()
        rate10 = len(self.raise_times)
        flood = rate10 > FLOOD_LIMIT
        if flood and not self._in_flood:
            self.flood_events += 1
        self._in_flood = flood
        standing = sum(1 for a in self.active.values() if ts - a.raised_ts > STANDING_AFTER_S and a.state != "rtn_unack")
        hours = max(ts / 3600.0, 1e-9)
        return {
            "active": len(self.active),
            "unacknowledged": sum(1 for a in self.active.values() if a.state in ("active_unack", "rtn_unack")),
            "rate_per_10min": rate10,
            "average_per_hour": round(self.total_raised / hours, 3),
            "flood_now": flood,
            "flood_events": self.flood_events,
            "standing": standing,
            "chattering_tags": sum(1 for v in self.chatter.values() if v >= 3),
            "total_raised": self.total_raised,
        }

    def listing(self) -> list[dict]:
        return sorted((a.to_dict() for a in self.active.values()),
                      key=lambda d: (PRIORITY_ORDER[d["priority"]], -d["raised_ts"]))
