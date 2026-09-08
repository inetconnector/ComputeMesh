from __future__ import annotations

from datetime import datetime
from html import unescape
from html.parser import HTMLParser
import json
import re
from typing import Iterable
from urllib.parse import urljoin
import xml.etree.ElementTree as ET

from .models import EventObservation

_WS = re.compile(r"\s+")
_JSONLD = re.compile(r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", re.I | re.S)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_ICS_LINE = re.compile(r"^([A-Z-]+)(?:;[^:]*)?:(.*)$")


class _TextLinkParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.text: list[str] = []
        self.links: list[str] = []
        self._ignore = 0

    def handle_starttag(self, tag: str, attrs):
        low = tag.lower()
        if low in {"script","style","noscript","svg"}:
            self._ignore += 1
        if low == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(urljoin(self.base_url, href))

    def handle_endtag(self, tag: str):
        if tag.lower() in {"script","style","noscript","svg"} and self._ignore:
            self._ignore -= 1

    def handle_data(self, data: str):
        if not self._ignore and data.strip():
            self.text.append(data.strip())


def html_snapshot(html: str, base_url: str) -> tuple[str,str,list[str],list[str]]:
    title_match = _TITLE.search(html)
    title = _WS.sub(" ", unescape(title_match.group(1))).strip() if title_match else ""
    parser = _TextLinkParser(base_url)
    try:
        parser.feed(html)
    except Exception:
        pass
    text = _WS.sub(" ", " ".join(parser.text)).strip()
    jsonld = [unescape(m.group(1)).strip() for m in _JSONLD.finditer(html) if m.group(1).strip()]
    return title,text,list(dict.fromkeys(parser.links)),jsonld


def _s(value) -> str | None:
    if value is None: return None
    if isinstance(value,str): return value.strip() or None
    if isinstance(value,(int,float)): return str(value)
    return None


def _date_time(value: str | None) -> tuple[str | None,str | None]:
    if not value: return None,None
    raw = value.strip()
    try:
        dt = datetime.fromisoformat(raw.replace("Z","+00:00"))
        return dt.date().isoformat(), dt.strftime("%H:%M") if "T" in raw or ":" in raw else None
    except ValueError:
        pass
    m = re.search(r"(20\d\d)[-/.](\d{1,2})[-/.](\d{1,2})",raw)
    if m: return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}",None
    m = re.search(r"(\d{1,2})[.]\s*(\d{1,2})[.]\s*(20\d\d)",raw)
    if m: return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}",None
    return None,None


def _iter_json_nodes(value):
    if isinstance(value,dict):
        yield value
        for child in value.values(): yield from _iter_json_nodes(child)
    elif isinstance(value,list):
        for child in value: yield from _iter_json_nodes(child)


def _is_event(node: dict) -> bool:
    typ = node.get("@type")
    if isinstance(typ,list): return any("event" in str(x).lower() for x in typ)
    return "event" in str(typ or "").lower()


def _location(node: dict) -> tuple[str,str | None,float | None,float | None]:
    loc = node.get("location")
    if isinstance(loc,str): return loc,None,None,None
    if not isinstance(loc,dict): return "Unknown venue",None,None,None
    name = _s(loc.get("name")) or "Unknown venue"
    address = loc.get("address")
    area = (_s(address.get("addressLocality")) or _s(address.get("addressRegion"))) if isinstance(address,dict) else (_s(address) if isinstance(address,str) else None)
    geo = loc.get("geo") if isinstance(loc.get("geo"),dict) else {}
    try:
        lat = float(geo.get("latitude")) if geo.get("latitude") is not None else None
        lon = float(geo.get("longitude")) if geo.get("longitude") is not None else None
    except (TypeError,ValueError):
        lat = lon = None
    return name,area,lat,lon


def _price(node: dict) -> str | None:
    offers = node.get("offers")
    for offer in offers if isinstance(offers,list) else [offers]:
        if isinstance(offer,dict):
            price = _s(offer.get("price")) or _s(offer.get("lowPrice"))
            currency = _s(offer.get("priceCurrency"))
            if price: return f"{price} {currency}".strip() if currency else price
    return None


def extract_jsonld(blocks: Iterable[str], *, source_url: str, source_name: str) -> list[EventObservation]:
    out: list[EventObservation] = []
    for block in blocks:
        try: root = json.loads(block)
        except json.JSONDecodeError: continue
        for node in _iter_json_nodes(root):
            if not _is_event(node): continue
            title = _s(node.get("name")); date_iso,start_time = _date_time(_s(node.get("startDate")))
            _,end_time = _date_time(_s(node.get("endDate")))
            if not title or not date_iso: continue
            venue,area,lat,lon = _location(node)
            status_raw = str(node.get("eventStatus") or "").lower()
            status = "cancelled" if "cancel" in status_raw else "postponed" if "postpon" in status_raw else "scheduled"
            event_url = _s(node.get("url")) or source_url
            out.append(EventObservation(title=title,venue=venue,date_iso=date_iso,source_url=source_url,source_name=source_name,
                event_url=urljoin(source_url,event_url),area=area,start_time=start_time,end_time=end_time,price=_price(node),
                description=_s(node.get("description")) or "",genre=_s(node.get("genre")),status=status,
                venue_latitude=lat,venue_longitude=lon,extraction_method="jsonld",confidence=.95))
    return out


def unfold_ics(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n","\n").split("\n"):
        if raw.startswith((" ","\t")) and lines: lines[-1] += raw[1:]
        else: lines.append(raw.rstrip("\r"))
    return lines


def _ics_datetime(raw: str | None) -> str | None:
    if not raw: return None
    for fmt in ("%Y%m%dT%H%M%SZ","%Y%m%dT%H%M%S","%Y%m%dT%H%M","%Y%m%d"):
        try: return datetime.strptime(raw.strip(),fmt).isoformat()
        except ValueError: pass
    return raw.strip()


def extract_ics(text: str, *, source_url: str, source_name: str) -> list[EventObservation]:
    out: list[EventObservation] = []; current: dict[str,str] | None = None
    for line in unfold_ics(text):
        if line == "BEGIN:VEVENT": current = {}; continue
        if line == "END:VEVENT":
            if current:
                title = current.get("SUMMARY","").strip(); date_iso,start_time = _date_time(_ics_datetime(current.get("DTSTART")))
                _,end_time = _date_time(_ics_datetime(current.get("DTEND")))
                if title and date_iso:
                    status = "cancelled" if "cancel" in current.get("STATUS","").lower() else "scheduled"
                    out.append(EventObservation(title=title,venue=current.get("LOCATION","Unknown venue").replace("\\,",","),date_iso=date_iso,
                        source_url=source_url,source_name=source_name,event_url=current.get("URL",source_url),start_time=start_time,end_time=end_time,
                        description=current.get("DESCRIPTION","").replace("\\n"," "),status=status,extraction_method="ics",confidence=.93))
            current = None; continue
        if current is not None:
            m = _ICS_LINE.match(line)
            if m: current[m.group(1)] = m.group(2)
    return out


def extract_feed(text: str, *, source_url: str, source_name: str) -> list[EventObservation]:
    try: root = ET.fromstring(text)
    except ET.ParseError: return []
    out: list[EventObservation] = []
    items = list(root.iter("item")) + [e for e in root.iter() if e.tag.endswith("entry")]
    for item in items:
        def child_text(names: tuple[str,...]) -> str | None:
            for ch in item.iter():
                if ch.tag.split("}")[-1].lower() in names and ch.text and ch.text.strip(): return ch.text.strip()
            return None
        title = child_text(("title",)); when = child_text(("startdate","date","published","updated")); date_iso,start_time = _date_time(when)
        if not title or not date_iso: continue
        link = source_url
        for ch in item.iter():
            if ch.tag.split("}")[-1].lower() == "link": link = ch.attrib.get("href") or (ch.text or link); break
        desc = child_text(("description","summary","content")) or ""
        out.append(EventObservation(title=title,venue="Unknown venue",date_iso=date_iso,source_url=source_url,source_name=source_name,
            event_url=urljoin(source_url,link),start_time=start_time,description=_WS.sub(" ",re.sub(r"<[^>]+>"," ",desc)).strip(),
            extraction_method="feed",confidence=.65))
    return out
