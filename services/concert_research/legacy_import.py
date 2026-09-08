from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

from .config import ConcertResearchConfig
from .crawler import ConcertCrawler
from .models import SourceRecord
from .storage import ConcertStore


def _entries(data: dict) -> Iterable[dict]:
    for key in ("event_directory_sources","venue_event_pages","festival_and_recurring_event_sources"):
        for item in data.get(key,[]) or []:
            if isinstance(item,dict):
                yield item


def import_seed_file(path: Path, crawler: ConcertCrawler) -> dict[str,int]:
    data=json.loads(path.read_text(encoding="utf-8")); city_data=data.get("city") or {}; city=str(city_data.get("name") or path.stem)
    counts={"sources":0,"created":0,"urls":0}; order={str(v):i+1 for i,v in enumerate(data.get("recommended_crawl_order",[]) or [])}
    for item in _entries(data):
        urls=[]
        if item.get("url"): urls.append(str(item["url"]))
        urls += [str(u) for u in (item.get("urls") or []) if u]
        strategy=item.get("crawler_strategy") or {}; urls += [str(u) for u in (strategy.get("also_crawl") or []) if u]
        if not urls: continue
        item_id=str(item.get("id") or ""); priority=int(item.get("priority") or order.get(item_id,50))
        item_type=str(item.get("type") or "legacy_seed")
        tier="primary" if priority<=1 or (item.get("verification_status")=="verified" and item_type.startswith(("official","venue"))) else "secondary"
        for url in dict.fromkeys(urls):
            _,created=crawler.seed_source(SourceRecord(name=str(item.get("name") or item_id or url),url=url,tier=tier,source_type=item_type,city=city,priority=priority,score=max(0,100-priority*5)))
            counts["urls"]+=1; counts["created"]+=int(created)
        counts["sources"]+=1
    return counts


def import_seed_directory(path: Path, crawler: ConcertCrawler) -> dict[str,int]:
    total={"files":0,"sources":0,"created":0,"urls":0}
    for file in sorted(path.glob("*.json")):
        try: stats=import_seed_file(file,crawler)
        except (OSError,json.JSONDecodeError,ValueError,TypeError): continue
        total["files"]+=1
        for key in ("sources","created","urls"): total[key]+=stats[key]
    return total


def discover_default_seed_dir() -> Path | None:
    here=Path(__file__).resolve()
    candidates=[here.parents[3]/"Today"/"HeuteUndMorgen"/"Data"/"crawler-seedlists",here.parents[4]/"Today"/"HeuteUndMorgen"/"Data"/"crawler-seedlists",Path.cwd().parent/"Today"/"HeuteUndMorgen"/"Data"/"crawler-seedlists"]
    return next((p for p in candidates if p.is_dir()),None)


def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("path",nargs="?"); args=parser.parse_args()
    cfg=ConcertResearchConfig.from_env(); crawler=ConcertCrawler(ConcertStore(cfg.db_path),cfg)
    seed_dir=Path(args.path) if args.path else discover_default_seed_dir()
    if not seed_dir: raise SystemExit("No seed directory found; pass it explicitly")
    print(json.dumps(import_seed_directory(seed_dir,crawler),indent=2)); return 0


if __name__=="__main__": raise SystemExit(main())
