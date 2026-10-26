"""Normalized data contracts.

Every data mode (simulation, hybrid, live) produces and consumes exactly these
messages. The twin engine never sees anything else, so swapping a data source
never touches the twin logic.
"""
from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field


class Mode(str, Enum):
    simulation = "simulation"
    hybrid = "hybrid"
    live = "live"


class _Msg(BaseModel):
    ts: float = Field(description="Timestamp, seconds (simulation clock or UNIX epoch)")
    source: str = Field(description="Sensor / provider identifier")


class SegmentObservation(_Msg):
    """Roadside station aggregate for one segment and travel direction.

    direction 0 = Lagos -> Ibadan (outbound), 1 = Ibadan -> Lagos (inbound).
    """
    type: Literal["segment_obs"] = "segment_obs"
    segment_id: int = Field(ge=0)
    direction: int = Field(ge=0, le=1)
    window_s: float = Field(gt=0)
    vehicle_count: int = Field(ge=0)
    truck_count: int = Field(ge=0)
    mean_speed_kmh: float = Field(ge=0, le=200)
    esal_per_truck: Optional[float] = Field(default=None, ge=0, description="From weigh-in-motion axle loads")
    mean_truck_gvw_t: Optional[float] = Field(default=None, ge=0, le=150)
    pavement_temp_c: Optional[float] = Field(default=None, ge=-20, le=90)


class ProbeObservation(_Msg):
    """A truck acting as a mobile roughness sensor over one segment."""
    type: Literal["probe_obs"] = "probe_obs"
    segment_id: int = Field(ge=0)
    vehicle_id: str
    iri_m_per_km: float = Field(ge=0, le=30)
    speed_kmh: float = Field(ge=0, le=200)
    impacts_m: list[float] = Field(default_factory=list, description="Chainage within segment of detected impacts")


class VehiclePosition(_Msg):
    type: Literal["vehicle_pos"] = "vehicle_pos"
    vehicle_id: str
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    speed_kmh: float = Field(ge=0, le=200)
    direction: int = Field(ge=0, le=1)
    gvw_t: Optional[float] = Field(default=None, ge=0, le=150)


class WeatherObservation(_Msg):
    type: Literal["weather_obs"] = "weather_obs"
    rain_mm_h: float = Field(ge=0, le=500)
    air_temp_c: float = Field(ge=-20, le=60)


class IncidentReport(_Msg):
    type: Literal["incident"] = "incident"
    segment_id: int = Field(ge=0)
    kind: Literal["accident", "breakdown", "closure", "flood", "roadworks"]
    severity: float = Field(ge=0, le=1)
    active: bool


class MaintenanceEvent(_Msg):
    """Work order completion, as exchanged with a maintenance system (ISA-95 style)."""
    type: Literal["maintenance"] = "maintenance"
    segment_id: int = Field(ge=0)
    action: Literal["patch", "resurface"]


Message = Annotated[
    Union[SegmentObservation, ProbeObservation, VehiclePosition, WeatherObservation,
          IncidentReport, MaintenanceEvent],
    Field(discriminator="type"),
]


class Batch(BaseModel):
    messages: list[Message] = Field(max_length=5000)
