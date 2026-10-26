"""FastAPI application: REST, WebSocket stream, signed ingestion, static dashboard."""
from __future__ import annotations

import asyncio
import hmac
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from .contracts import Batch, Mode
from .runtime import Runtime

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


class ControlIn(BaseModel):
    speed: Optional[int] = Field(default=None, ge=1, le=288)
    paused: Optional[bool] = None


class ScenarioIn(BaseModel):
    kind: Literal["closure", "accident", "overload", "rain", "sensor_outage"]
    segment_id: Optional[int] = Field(default=None, ge=0)
    direction: int = Field(default=0, ge=0, le=1)
    hours: float = Field(default=4.0, gt=0, le=240)
    days: float = Field(default=7.0, gt=0, le=60)
    mult: float = Field(default=1.3, ge=1.0, le=2.0)
    ticks: int = Field(default=60, ge=1, le=1000)


class WorkOrderIn(BaseModel):
    segment_id: int = Field(ge=0)
    action: Literal["patch", "resurface"]


def create_app(rt: Runtime) -> FastAPI:
    clients: set[WebSocket] = set()

    async def loop():
        while True:
            await asyncio.sleep(0.5)
            if rt.mode == Mode.live:
                rt.evaluate_live()
            elif not rt.paused:
                await asyncio.to_thread(rt.advance, max(1, round(rt.speed * 0.5)))
            if clients:
                payload = json.dumps(rt.snapshot(include_truth=rt.world is not None))
                for ws in list(clients):
                    try:
                        await ws.send_text(payload)
                    except Exception:
                        clients.discard(ws)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(loop())
        yield
        task.cancel()

    app = FastAPI(title="RouteTwin NG", version="0.1.0", lifespan=lifespan)
    app.state.rt = rt

    def operator(x_operator_token: str | None = Header(default=None)):
        if rt.operator_token is None:
            return  # simulation demo only (non-simulation modes refuse to start without a token)
        if not x_operator_token or not hmac.compare_digest(x_operator_token, rt.operator_token):
            rt.audit.write("auth_denied", scope="operator")
            raise HTTPException(401, "operator token required")

    @app.get("/healthz")
    def healthz():
        return {"status": "ok", "mode": rt.mode.value}

    @app.get("/api/config")
    def config():
        return rt.config()

    @app.get("/api/state")
    def state(truth: bool = False):
        return rt.snapshot(include_truth=truth and rt.world is not None)

    @app.get("/api/segment/{segment_id}/history")
    def history(segment_id: int):
        if not 0 <= segment_id < rt.cor.n:
            raise HTTPException(404, "unknown segment")
        return rt.history(segment_id)

    @app.post("/api/control", dependencies=[Depends(operator)])
    def control(body: ControlIn):
        if body.speed is not None:
            rt.speed = body.speed
        if body.paused is not None:
            rt.paused = body.paused
        rt.audit.write("control", speed=rt.speed, paused=rt.paused)
        return {"speed": rt.speed, "paused": rt.paused}

    @app.post("/api/scenario", dependencies=[Depends(operator)])
    def scenario(body: ScenarioIn):
        kw = body.model_dump(exclude_none=True)
        kind = kw.pop("kind")
        if kind in ("closure", "accident", "sensor_outage") and body.segment_id is None:
            raise HTTPException(422, "segment_id required")
        if kind in ("closure", "accident", "sensor_outage") and body.segment_id >= rt.cor.n:
            raise HTTPException(404, "unknown segment")
        try:
            rt.trigger(kind, **kw)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"ok": True}

    @app.post("/api/alarms/{alarm_id}/ack", dependencies=[Depends(operator)])
    def ack(alarm_id: int):
        if not rt.ack(alarm_id):
            raise HTTPException(404, "alarm not active")
        return {"ok": True}

    @app.post("/api/alarms/ack_all", dependencies=[Depends(operator)])
    def ack_all():
        return {"acknowledged": rt.ack_all()}

    @app.post("/api/workorder", dependencies=[Depends(operator)])
    def workorder(body: WorkOrderIn):
        try:
            rt.work_order(body.segment_id, body.action)
        except ValueError as e:
            raise HTTPException(404, str(e))
        return {"ok": True}

    @app.post("/api/ingest")
    async def ingest(request: Request, x_timestamp: str | None = Header(default=None),
                     x_signature: str | None = Header(default=None)):
        if rt.verifier is None:
            raise HTTPException(404, "ingestion is enabled only in live mode")
        body = await request.body()
        ok, reason = rt.verifier.verify(x_timestamp or "", x_signature or "", body)
        if not ok:
            rt.audit.write("ingest_rejected", reason=reason)
            raise HTTPException(401, reason)
        try:
            batch = Batch.model_validate_json(body)
        except ValidationError as e:
            rt.audit.write("ingest_invalid", errors=len(e.errors()))
            raise HTTPException(422, json.loads(e.json())[:5])
        with rt.lock:
            rt.engine.ingest(batch.messages)
        return {"accepted": len(batch.messages)}

    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
        await websocket.accept()
        clients.add(websocket)
        try:
            await websocket.send_text(json.dumps(rt.snapshot(include_truth=rt.world is not None)))
            while True:
                await websocket.receive_text()
        except (WebSocketDisconnect, Exception):
            clients.discard(websocket)

    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
    return app
