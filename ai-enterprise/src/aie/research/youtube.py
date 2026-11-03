"""YouTube Data API v3 som källa för scouten och 7a (Robin 2026-10-30). Bara läsande anrop.

För ett sökord görs tre anrop via `WebReader` (tillåtna värdar, dagskvot, inget sparat om nyckeln):
1. `search.list` (100 enheter): de mest visade videorna om sökordet.
2. `search.list` med `publishedAfter` 90 dagar bakåt (100 enheter): `pageInfo.totalResults` är trenden,
   alltså hur många nya videor som kommit ut.
3. `videos.list` (1 enhet): visningar, gillamarkeringar, uppladdningsdatum och beskrivning.

Koden bygger signalerna själv ur svaret; ingen modell tolkar siffrorna. Butikslänkar i beskrivningarna
(värdar ur `shop_hosts` i config) blir prissignaler när ett pris står i närheten. Nyckeln skickas bara som
rubrik (`X-goog-api-key`) till API:ets värd och loggas aldrig.
"""

from __future__ import annotations

import json
import re
import urllib.parse
from dataclasses import dataclass
from datetime import date, timedelta

from ..pilot.discovery import Signal

API = "https://www.googleapis.com/youtube/v3"
UNITS_PER_QUERY = 201  # två search.list och en videos.list
_PRICE = re.compile(
    r"(?:\$|USD\s?)(\d{1,4}(?:[.,]\d{2})?)|(\d{1,4}(?:[.,]\d{2})?)\s?(?:USD|\$|kr|SEK|€|EUR)"
)
_URL = re.compile(r"https?://[^\s)\"'<>]+")


@dataclass(frozen=True, slots=True)
class YouTubeConfig:
    max_queries: (
        int  # per körning; dagskvoten 10 000 enheter räcker till cirka 49 sökord
    )
    daily_units: int
    top_videos: int
    shop_hosts: tuple[str, ...]


class YouTubeSource:
    def __init__(
        self, reader, agent: str, key: str, cfg: YouTubeConfig, today: date
    ) -> None:
        self._reader, self._agent, self._cfg, self._today = reader, agent, cfg, today
        self._headers = {"X-goog-api-key": key}
        self.units = 0
        self.log: list[str] = []

    def _get(self, url: str) -> tuple[dict, object]:
        page = self._reader.fetch(self._agent, url, self._headers)
        return json.loads(page.content.content), page

    def collect(self, term: str, start: int) -> list[Signal]:
        """Signaler om ett sökord. Tom lista när kvoten är slut eller API:et svarar fel; det loggas."""
        if (
            self.units + UNITS_PER_QUERY > self._cfg.daily_units
            or self._cfg.max_queries <= 0
        ):
            self.log.append(
                f"YouTube: kvoten för körningen är nådd, {term!r} hoppades över"
            )
            return []
        self._cfg = YouTubeConfig(
            self._cfg.max_queries - 1,
            self._cfg.daily_units,
            self._cfg.top_videos,
            self._cfg.shop_hosts,
        )
        q = urllib.parse.quote_plus(term)
        try:
            top, _page = self._get(
                f"{API}/search?part=snippet&type=video&order=viewCount&maxResults="
                f"{self._cfg.top_videos}&q={q}"
            )
            after = (self._today - timedelta(days=90)).isoformat() + "T00:00:00Z"
            recent, recent_page = self._get(
                f"{API}/search?part=id&type=video&maxResults=1&publishedAfter={after}&q={q}"
            )
            ids = ",".join(
                i["id"]["videoId"]
                for i in top.get("items", [])
                if i.get("id", {}).get("videoId")
            )
            stats, stats_page = (
                self._get(f"{API}/videos?part=snippet,statistics&id={ids}")
                if ids
                else ({}, None)
            )
        except Exception as exc:  # noqa: BLE001 — loggas utan nyckel; ingen signal hittas på
            self.log.append(f"YouTube {term!r}: {type(exc).__name__}: {str(exc)[:120]}")
            return []
        finally:
            self.units += UNITS_PER_QUERY
        out: list[Signal] = []

        def add(kind, title, quote, url, fetch_id, price=None, count=None):
            out.append(
                Signal(
                    f"S{start + len(out)}",
                    url,
                    fetch_id,
                    kind,
                    title[:160],
                    quote[:160],
                    price,
                    count,
                )
            )

        new_90 = recent.get("pageInfo", {}).get("totalResults")
        if isinstance(new_90, int):
            add(
                "competitor",
                f"YouTube: {new_90} nya videor senaste 90 dagarna om {term}",
                term,
                recent_page.final_url,
                recent_page.fetch_id,
                count=new_90,
            )
        for v in stats.get("items", []):
            sn, st = v.get("snippet", {}), v.get("statistics", {})
            views, likes = int(st.get("viewCount", 0) or 0), st.get("likeCount")
            title = sn.get("title", "")
            url = f"https://www.youtube.com/watch?v={v.get('id')}"
            add(
                "competitor",
                f"YouTube-video om {term}: {views} visningar, {likes or '?'} gillamarkeringar, "
                f"uppladdad {sn.get('publishedAt', '')[:10]}: {title}",
                title,
                url,
                stats_page.fetch_id,
                count=views,
            )
            for link in _URL.findall(sn.get("description", "")):
                host = (urllib.parse.urlsplit(link).hostname or "").lower()
                if not any(
                    host == h or host.endswith("." + h) for h in self._cfg.shop_hosts
                ):
                    continue
                near = sn["description"][
                    max(0, sn["description"].find(link) - 80) : sn["description"].find(
                        link
                    )
                    + 80
                ]
                m = _PRICE.search(near)
                price = (
                    round(float((m.group(1) or m.group(2)).replace(",", ".")) * 100)
                    if m
                    else None
                )
                add(
                    "price" if price is not None else "competitor",
                    f"Butikslänk i YouTube-video om {term}: {title}",
                    link,
                    link,
                    stats_page.fetch_id,
                    price=price,
                    count=None if price is not None else views,
                )
        return out


def numbers(signals: list[Signal]) -> dict:
    """Sammanfattning för rapporten: visningar i toppvideorna, trenden och butikspriser."""
    views = [
        s.count
        for s in signals
        if s.title.startswith("YouTube-video") and s.count is not None
    ]
    trend = [
        s.count
        for s in signals
        if "nya videor senaste 90" in s.title and s.count is not None
    ]
    prices = [
        s.price_cents
        for s in signals
        if s.kind == "price" and s.price_cents is not None
    ]
    return {
        "top_views": max(views, default=None),
        "median_views": sorted(views)[len(views) // 2] if views else None,
        "new_videos_90d": max(trend, default=None),
        "shop_prices_cents": prices[:5],
    }


def from_env(reader, agent: str, config_dir, environ, today: date):
    """(källa, initiala sökord, notis). Utan YOUTUBE_API_KEY hoppas källan över, och det står i notisen."""
    import tomllib
    from pathlib import Path

    key = environ.get("YOUTUBE_API_KEY")
    if not key:
        return None, 0, "YouTube: YOUTUBE_API_KEY saknas, källan hoppades över"
    y = tomllib.loads((Path(config_dir) / "pilot.toml").read_text(encoding="utf-8"))["youtube"]
    cfg = YouTubeConfig(int(y["max_queries"]), int(y["daily_units"]), int(y["top_videos"]), tuple(y["shop_hosts"]))
    return YouTubeSource(reader, agent, key, cfg, today), int(y["initial_terms"]), None


def enrich(ideas, by_id: dict, source: YouTubeSource) -> None:
    """Söker på varje idés titel och kopplar bara signaler som handlar om samma sak (kod, inte modell)."""
    from ..pilot.discovery import _words

    for idea in ideas:
        found = source.collect(idea.title, max((int(k[1:]) for k in by_id), default=0) + 1)
        words = _words(idea.title)
        for s in found:
            by_id[s.id] = s
            if words & _words(f"{s.title} {s.quote}"):
                idea.signal_ids = (*idea.signal_ids, s.id)
