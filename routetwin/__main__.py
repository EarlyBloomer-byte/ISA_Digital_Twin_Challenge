"""python -m routetwin --mode simulation|hybrid|live"""
import argparse
import os

import uvicorn

from .api import create_app
from .runtime import Runtime


def main():
    ap = argparse.ArgumentParser(description="RouteTwin NG digital twin server")
    ap.add_argument("--mode", default=os.getenv("ROUTETWIN_MODE", "simulation"), choices=["simulation", "hybrid", "live"])
    ap.add_argument("--seed", type=int, default=int(os.getenv("ROUTETWIN_SEED", "42")))
    ap.add_argument("--host", default=os.getenv("ROUTETWIN_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.getenv("ROUTETWIN_PORT", "8000")))
    ap.add_argument("--no-demo-script", action="store_true", help="disable the scripted demo events")
    ap.add_argument("--weather-file", default=os.getenv("ROUTETWIN_WEATHER_FILE"))
    ap.add_argument("--corridor", default=os.getenv("ROUTETWIN_CORRIDOR"))
    ap.add_argument("--audit-log", default=os.getenv("ROUTETWIN_AUDIT_LOG", "audit.log"))
    a = ap.parse_args()
    rt = Runtime(a.mode, seed=a.seed, corridor_path=a.corridor, weather_file=a.weather_file,
                 demo_script=not a.no_demo_script, audit_path=a.audit_log,
                 ingest_key=os.getenv("ROUTETWIN_INGEST_KEY"), operator_token=os.getenv("ROUTETWIN_OPERATOR_TOKEN"))
    uvicorn.run(create_app(rt), host=a.host, port=a.port, log_level="info")


if __name__ == "__main__":
    main()
