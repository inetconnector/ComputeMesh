from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import sys
from typing import Any

from .engine import ConcertResearchEngine
from .models import ResearchRequest

PROTOCOL_VERSION = "2026-07-28"

RESEARCH_SCHEMA = {
    "type":"object","properties":{
        "city":{"type":"string"},"city_slug":{"type":["string","null"]},"postal_code":{"type":["string","null"]},
        "latitude":{"type":["number","null"]},"longitude":{"type":["number","null"]},"radius_km":{"type":"number","default":50},
        "date_from":{"type":["string","null"]},"date_to":{"type":["string","null"]},"query_date":{"type":["string","null"]},
        "day_scope":{"type":"string","default":"today_tomorrow"},"genre_profile_key":{"type":["string","null"]},
        "genre_terms":{"type":"array","items":{"type":"string"}},"force_refresh":{"type":"boolean","default":False},
        "max_events":{"type":"integer","minimum":1,"maximum":200,"default":50}},
    "required":["city"],"additionalProperties":False}

TOOLS = [
    {"name":"research_concerts","description":"Query the persistent ComputeMesh concert index and optionally refresh it using the first-party crawler and ComputeMesh Fleet AI.","inputSchema":RESEARCH_SCHEMA},
    {"name":"concert_refresh_city","description":"Owner/operator tool: run source discovery and a crawl cycle for a city.","inputSchema":{"type":"object","properties":{"city":{"type":"string"},"genre_terms":{"type":"array","items":{"type":"string"}}},"required":["city"],"additionalProperties":False}},
    {"name":"concert_source_status","description":"Owner/operator tool: list known concert sources for a city.","inputSchema":{"type":"object","properties":{"city":{"type":"string"}},"required":["city"],"additionalProperties":False}},
]


class MCPApplication:
    def __init__(self, engine: ConcertResearchEngine | None = None): self.engine=engine or ConcertResearchEngine()

    def handle(self, payload: dict[str,Any]) -> dict[str,Any] | None:
        method=payload.get("method"); req_id=payload.get("id")
        if method=="notifications/initialized": return None
        try:
            if method=="initialize": result={"protocolVersion":PROTOCOL_VERSION,"capabilities":{"tools":{"listChanged":False}},"serverInfo":{"name":"ComputeMesh Concert Research","version":"1.0.0"}}
            elif method=="tools/list": result={"tools":TOOLS}
            elif method=="tools/call":
                params=payload.get("params") or {}; result=self.call_tool(str(params.get("name") or ""),params.get("arguments") or {})
            elif method=="ping": result={}
            else: raise KeyError(f"Unknown method: {method}")
            return {"jsonrpc":"2.0","id":req_id,"result":result}
        except Exception as exc:
            return {"jsonrpc":"2.0","id":req_id,"error":{"code":-32000,"message":str(exc)}}

    def call_tool(self, name: str, args: dict[str,Any]) -> dict[str,Any]:
        if name=="research_concerts":
            req=ResearchRequest(city=str(args["city"]),radius_km=float(args.get("radius_km",50)),latitude=args.get("latitude"),longitude=args.get("longitude"),
                postal_code=args.get("postal_code"),city_slug=args.get("city_slug"),date_from=args.get("date_from"),date_to=args.get("date_to"),query_date=args.get("query_date"),
                day_scope=str(args.get("day_scope") or "today_tomorrow"),genre_profile_key=args.get("genre_profile_key"),genre_terms=[str(x) for x in args.get("genre_terms",[])],
                force_refresh=bool(args.get("force_refresh",False)),max_events=max(1,min(200,int(args.get("max_events",50)))))
            structured=self.engine.research(req)
            return {"content":[{"type":"text","text":json.dumps(structured,ensure_ascii=False)}],"structuredContent":structured,"isError":False}
        if name=="concert_refresh_city":
            result=self.engine.daily_cycle(str(args["city"]),genre_terms=[str(x) for x in args.get("genre_terms",[])])
            return {"content":[{"type":"text","text":json.dumps(result,ensure_ascii=False)}],"structuredContent":result,"isError":False}
        if name=="concert_source_status":
            rows=self.engine.store.sources_for_city(str(args["city"])); result=[{"name":r['name'],"url":r['canonical_url'],"tier":r['tier'],"type":r['source_type'],"score":r['score'],"last_crawled":r['last_crawled'],"event_yield":r['event_yield']} for r in rows]
            return {"content":[{"type":"text","text":json.dumps(result,ensure_ascii=False)}],"structuredContent":{"sources":result},"isError":False}
        raise KeyError(f"Unknown tool: {name}")


def run_stdio(app: MCPApplication) -> None:
    for line in sys.stdin:
        line=line.strip()
        if not line: continue
        try: payload=json.loads(line)
        except json.JSONDecodeError: continue
        response=app.handle(payload)
        if response is not None:
            sys.stdout.write(json.dumps(response,ensure_ascii=False)+"\n"); sys.stdout.flush()


class HTTPHandler(BaseHTTPRequestHandler):
    app: MCPApplication | None = None
    server_version="ComputeMesh-Concert-MCP/1.0"; sys_version=""
    def log_message(self,*_): pass
    @classmethod
    def require_app(cls) -> MCPApplication:
        if cls.app is None:
            raise RuntimeError("Concert MCP application is not initialized")
        return cls.app
    def do_GET(self):
        if self.path=="/healthz": self._json({"status":"healthy","service":"concert-research","protocolVersion":PROTOCOL_VERSION})
        else: self.send_error(404)
    def do_POST(self):
        if self.path not in {"/mcp","/"}: self.send_error(404); return
        try:
            length=min(int(self.headers.get("Content-Length","0")),2*1024*1024); payload=json.loads(self.rfile.read(length).decode())
            response=self.require_app().handle(payload)
            if response is None: self.send_response(202); self.end_headers(); return
            self._json(response)
        except Exception as exc: self._json({"jsonrpc":"2.0","id":None,"error":{"code":-32700,"message":str(exc)}},400)
    def _json(self,data,status=200):
        body=json.dumps(data,ensure_ascii=False).encode(); self.send_response(status); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(body))); self.send_header("Cache-Control","no-store"); self.end_headers(); self.wfile.write(body)


def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("--transport",choices=("stdio","http"),default="stdio"); parser.add_argument("--host",default="127.0.0.1"); parser.add_argument("--port",type=int,default=8098); parser.add_argument("--bootstrap-seeds",action="store_true"); args=parser.parse_args()
    app=MCPApplication()
    if args.bootstrap_seeds: app.engine.bootstrap_legacy_seeds()
    if args.transport=="stdio": run_stdio(app)
    else: HTTPHandler.app=app; ThreadingHTTPServer((args.host,args.port),HTTPHandler).serve_forever()
    return 0


if __name__=="__main__": raise SystemExit(main())
