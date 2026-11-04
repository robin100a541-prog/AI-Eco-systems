"""Etsy, Pinterest och Instagram (arbetsorder 04, D-068, D-069). Konton och nycklar finns inte än.
Klienterna är byggda och testade mot mockar, och avstängda.

En klient används bara när **allt** detta gäller. Annars kastas `Unavailable` med skälet, och inget skickas.
1. Tjänsten är påslagen i `config/pod.toml` (`enabled = true`).
2. Nyckeln finns i miljön, och för konton en token från `aie connect`.
3. Agenten har verktyget i `permissions.toml`. Authorization Engine avgör det, så nödstoppet och skyddat läge gäller.
4. **För skrivande anrop** ryms dagens antal i gränsen. Platsen reserveras atomärt i `pod_actions` (migration 38) före anropet.

**Lästa och verifierade 2026-11-04:**
- **Etsy Open API v3:**
  - bas `https://openapi.etsy.com/v3/application`
  - `x-api-key: keystring:shared_secret` på varje anrop, och OAuth-token för butikens egna data
  - `listings/active?keywords=` för sökning, och `listings/{id}/reviews` för recensioner
  - antalet som har favoritmarkerat (`num_favorers`) finns på listningen
  - kundmeddelanden finns inte i API:t
- **Pinterest API v5:**
  - `GET /v5/trends/keywords/{region}/top/{trend_type}`, högst 50 sökord per anrop och bara dagens data
  - Trends riktar sig till byråer, enterprise och partner, så det är **inte säkert** att vår app får tillgång
  - riktlinjerna tillåter inte att data från API:t sparas, utom kampanjstatistik, så trenderna används direkt och sparas inte
  - `POST /v5/pins` med `media_source` av typen `image_url` och en länk
- **Instagram Graph API (Instagram Login):**
  - först `POST /{ig-id}/media` med `image_url` (**bara JPEG**, från en publik adress), sedan `POST /{ig-id}/media_publish`
  - en karusell har högst 20 bilder och räknas som ett inlägg
  - Metas gräns anges till både 50 och 100 per 24 h, och klienten stannar alltid vid `HARD_DAILY_CAP` = 50
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import UTC, datetime
from urllib.parse import urlsplit

from .http import JsonClient, Transport, urllib_transport

HARD_DAILY_CAP = {"instagram": 50}  # Metas egen gräns; vår gräns i pod.toml är lägre
TREND_TYPES = ("growing", "monthly", "yearly", "seasonal")


class Unavailable(RuntimeError):
    """Tjänsten får inte användas just nu. Skälet står i meddelandet."""


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


class ActionLog:
    """Gränser per dygn för skrivande anrop. Räkning och reservation sker i samma transaktion (migration 38)."""

    def __init__(self, db, clock=_today) -> None:
        self._db, self._clock = db, clock

    def reserve(self, service: str, action: str, agent: str, ref: str, limit: int) -> int:
        day = self._clock()
        with self._db.transaction() as tx:
            (used,) = tx.execute("SELECT COUNT(*) FROM pod_actions WHERE service = ? AND action = ? AND day = ?",
                                 (service, action, day)).fetchone()
            if used >= limit:
                raise Unavailable(f"{service} {action}: dagens gräns {limit} är nådd")
            tx.execute("INSERT INTO pod_actions (service, action, day, agent, ref, at) VALUES (?, ?, ?, ?, ?, ?)",
                       (service, action, day, agent, ref, datetime.now(UTC).isoformat(timespec="seconds")))
        return used + 1

    def used(self, service: str, action: str) -> int:
        (n,) = self._db.connection.execute("SELECT COUNT(*) FROM pod_actions WHERE service = ? AND action = ? AND day = ?",
                                           (service, action, self._clock())).fetchone()
        return n


class _Channel:
    service = ""

    def __init__(self, engine, audit, agent_id: str, config: dict, client: JsonClient) -> None:
        self._engine, self._audit, self._agent, self._client = engine, audit, agent_id, client
        self._config = config.get(self.service, {})
        if not self._config.get("enabled", False):
            raise Unavailable(f"{self.service} är avstängt i config/pod.toml")

    def _require(self, tool: str) -> None:
        self._engine.require(self._agent, tool)


# --- Etsy ----------------------------------------------------------------------------------------

def etsy_client(environ: Mapping[str, str] = os.environ, token: str | None = None,
                transport: Transport = urllib_transport) -> JsonClient:
    key = environ.get("ETSY_API_KEY", "")
    if ":" not in key:
        raise Unavailable("ETSY_API_KEY saknas eller saknar shared secret (keystring:shared_secret)")
    headers = {"x-api-key": key, **({"Authorization": f"Bearer {token}"} if token else {})}
    return JsonClient("https://openapi.etsy.com", headers, transport=transport, min_interval=0.2)


class EtsySignals(_Channel):
    """`etsy.read`: offentliga listningar och recensioner som marknadssignal till scouten."""
    service = "etsy"

    def search(self, keywords: str, limit: int = 25) -> dict:
        self._require("etsy.read")
        data = self._client.get("/v3/application/listings/active",
                                {"keywords": keywords, "limit": min(int(limit), 100), "sort_on": "score"})
        results = data.get("results", []) if isinstance(data, dict) else []
        prices = [r["price"]["amount"] / r["price"]["divisor"] for r in results
                  if isinstance(r.get("price"), dict) and r["price"].get("divisor")]
        signal = {"keywords": keywords, "count": data.get("count") if isinstance(data, dict) else None,
                  "sampled": len(results), "median_price": sorted(prices)[len(prices) // 2] if prices else None,
                  "favorers": sum(int(r.get("num_favorers") or 0) for r in results),
                  "source": "openapi.etsy.com listings/active", "read_on": _today()}
        self._audit.append(self._agent, "etsy.read", {"keywords": keywords, "sampled": signal["sampled"]})
        return signal

    def reviews(self, listing_id: int, limit: int = 25) -> list[dict]:
        self._require("etsy.read")
        data = self._client.get(f"/v3/application/listings/{int(listing_id)}/reviews", {"limit": min(int(limit), 100)})
        rows = data.get("results", []) if isinstance(data, dict) else []
        self._audit.append(self._agent, "etsy.read", {"listing_id": int(listing_id), "reviews": len(rows)})
        return [{"rating": r.get("rating"), "review": r.get("review", "")} for r in rows]


# --- Pinterest -----------------------------------------------------------------------------------

def pinterest_client(token: str | None, transport: Transport = urllib_transport) -> JsonClient:
    if not token:
        raise Unavailable("ingen Pinterest-token; kör python -m aie connect pinterest")
    return JsonClient("https://api.pinterest.com", {"Authorization": f"Bearer {token}"}, transport=transport)


class PinterestTrends(_Channel):
    """`pinterest.trends`: dagens trendande sökord. Används direkt och sparas inte (Pinterests riktlinjer)."""
    service = "pinterest"

    def top(self, trend_type: str = "growing", region: str | None = None, limit: int = 50) -> list[dict]:
        if trend_type not in TREND_TYPES:
            raise ValueError(f"trend_type ska vara {', '.join(TREND_TYPES)}")
        region = region or self._config.get("trends_region", "US")
        if not (len(region) == 2 and region.isalpha()):
            raise ValueError("region ska vara en landskod med två bokstäver")
        self._require("pinterest.trends")
        data = self._client.get(f"/v5/trends/keywords/{region.upper()}/top/{trend_type}", {"limit": min(int(limit), 50)})
        trends = data.get("trends", []) if isinstance(data, dict) else []
        self._audit.append(self._agent, "pinterest.trends", {"region": region, "type": trend_type, "count": len(trends)})
        return [{"keyword": t.get("keyword"), "growth_wow": t.get("pct_growth_wow"),
                 "growth_mom": t.get("pct_growth_mom"), "growth_yoy": t.get("pct_growth_yoy")} for t in trends]


class PinterestPinner(_Channel):
    """`pinterest.pin`: en pin med länk till en egen Etsy-annons, högst `max_pins_per_day` per dygn (D-069)."""
    service = "pinterest"

    def __init__(self, engine, audit, agent_id, config, client, actions: ActionLog) -> None:
        super().__init__(engine, audit, agent_id, config, client)
        self._actions = actions

    def pin(self, board_id: str, title: str, description: str, link: str, image_url: str) -> dict:
        host = urlsplit(link).hostname or ""
        if not link.startswith("https://") or not (host == "etsy.com" or host.endswith(".etsy.com")):
            raise ValueError("en pin får bara länka till en Etsy-annons (https://…etsy.com/…)")
        if not image_url.startswith("https://"):
            raise ValueError("bilden ska ha en publik https-adress")
        self._require("pinterest.pin")
        self._actions.reserve("pinterest", "pin", self._agent, link, int(self._config.get("max_pins_per_day", 0)))
        data = self._client.post("/v5/pins", {"board_id": board_id, "title": title[:100], "description": description[:500],
                                              "link": link, "media_source": {"source_type": "image_url", "url": image_url}})
        self._audit.append(self._agent, "pinterest.pin", {"link": link, "id": (data or {}).get("id")})
        return data


# --- Instagram -----------------------------------------------------------------------------------

def instagram_client(token: str | None, transport: Transport = urllib_transport) -> JsonClient:
    if not token:
        raise Unavailable("ingen Instagram-token; kör python -m aie connect instagram")
    return JsonClient("https://graph.instagram.com", {"Authorization": f"Bearer {token}"}, transport=transport)


class InstagramPublisher(_Channel):
    """`instagram.publish`: en bild eller en karusell (högst 20) från publika JPEG-adresser."""
    service = "instagram"

    def __init__(self, engine, audit, agent_id, config, client, actions: ActionLog, ig_user_id: str) -> None:
        super().__init__(engine, audit, agent_id, config, client)
        self._actions, self._ig = actions, str(ig_user_id)
        if not self._ig.isdigit():
            raise ValueError("ig_user_id ska vara kontots numeriska id")

    def publish(self, image_urls: list[str], caption: str) -> dict:
        if not 1 <= len(image_urls) <= 20:
            raise ValueError("en till 20 bilder")
        for url in image_urls:
            if not url.startswith("https://") or not url.lower().split("?")[0].endswith((".jpg", ".jpeg")):
                raise ValueError("Instagram tar bara JPEG från en publik https-adress")
        self._require("instagram.publish")
        limit = min(int(self._config.get("max_posts_per_day", 0)), HARD_DAILY_CAP["instagram"])
        self._actions.reserve("instagram", "post", self._agent, image_urls[0], limit)
        version = self._config.get("api_version", "v23.0")
        base = f"/{version}/{self._ig}"
        if len(image_urls) == 1:
            container = self._client.post(f"{base}/media", {"image_url": image_urls[0], "caption": caption})
        else:
            children = [self._client.post(f"{base}/media", {"image_url": u, "is_carousel_item": True})["id"]
                        for u in image_urls]
            container = self._client.post(f"{base}/media", {"media_type": "CAROUSEL", "children": ",".join(children),
                                                            "caption": caption})
        data = self._client.post(f"{base}/media_publish", {"creation_id": container["id"]})
        self._audit.append(self._agent, "instagram.publish", {"images": len(image_urls), "id": (data or {}).get("id")})
        return data
