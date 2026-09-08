from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
import time
from .config import ConcertResearchConfig, resolve_timezone
from .engine import ConcertResearchEngine


def seconds_until_hour(hour: int, timezone_name: str) -> float:
    tz=resolve_timezone(timezone_name); now=datetime.now(tz); target=now.replace(hour=hour,minute=0,second=0,microsecond=0)
    if target<=now: target+=timedelta(days=1)
    return max(1.0,(target-now).total_seconds())


def run_once(engine: ConcertResearchEngine, city: str | None = None) -> list[dict]:
    cities=[city] if city else [row['name'] for row in engine.store.known_cities()]
    return [engine.daily_cycle(name) for name in cities]


def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("--once",action="store_true"); parser.add_argument("--city"); parser.add_argument("--bootstrap-seeds",action="store_true"); args=parser.parse_args()
    cfg=ConcertResearchConfig.from_env(); engine=ConcertResearchEngine(cfg)
    if args.bootstrap_seeds: print(json.dumps(engine.bootstrap_legacy_seeds(),ensure_ascii=False))
    if args.once: print(json.dumps(run_once(engine,args.city),ensure_ascii=False,indent=2)); return 0
    while True:
        time.sleep(seconds_until_hour(cfg.daily_hour_local,cfg.timezone)); run_once(engine,args.city)


if __name__=="__main__": raise SystemExit(main())
