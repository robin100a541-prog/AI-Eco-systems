"""Printify (arbetsorder 04, D-065). Verifierat mot developers.printify.com 2026-11-04:

- **Bas och nyckel:** bas-URL `https://api.printify.com/v1/`, med rubriken `Authorization: Bearer <token>`. Personliga tokens gäller ett år.
- **User-Agent** krävs på varje anrop.
- **Gränser:**
  - 600 anrop per minut totalt
  - 100 per minut mot katalogen
  - 200 publiceringar per 30 minuter
  - HTTP 429 när en gräns överskrids
  - felsvar får vara högst 5 % av anropen
- **Katalog:**
  - `GET /v1/catalog/blueprints.json`
  - `…/blueprints/{id}/print_providers.json`
  - `…/print_providers/{pp}/variants.json`
  - **Frakt** i v2: `GET /v2/catalog/blueprints/{id}/print_providers/{pp}/shipping/standard.json`. Svaret har ett land per rad och `shippingCost.firstItem.amount` i cent.
- **Baspris:** katalogens varianter har inget pris. Kostnaden i cent finns bara på en produkts varianter (`cost`). Det verkliga baspriset kräver därför en produkt i butiken, till exempel ett opublicerat utkast (`printify.draft`, avstängt tills D-069 är godkänt).
- **Bilder:** `POST /v1/uploads/images.json` med `url` eller base64 i `contents`.
  - URL rekommenderas över 5 MB, och base64 över 5 MB tas bort i framtiden.
  - Typerna är `image/png`, `image/jpg` och `image/jpeg`. SVG nämns inte.
  - För låg upplösning ger ett DPI-fel.
- **Produkt:** `POST /v1/shops/{shop}/products.json` skapar produkten. Den hamnar inte i en butik förrän `…/publish.json` anropas. Den här modulen anropar **aldrig** publicering.

Verktygen (Authorization Engine):
- `printify.read`: allt som bara läser.
- `printify.draft`: skapa en opublicerad produkt och ladda upp en bild. Det kräver dessutom
  `[printify] draft_enabled = true` i `config/pod.toml`. Det är `false` tills D-069 är godkänt.
"""
from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from pathlib import Path

from .http import ApiError, JsonClient, Transport, urllib_transport

BASE_URL = "https://api.printify.com"
TOKEN_ENV = "PRINTIFY_API_TOKEN"
READ, DRAFT, PUBLISH = "printify.read", "printify.draft", "printify.publish"
IMAGE_TYPES = ("image/png", "image/jpeg")  # SVG nämns inte i dokumentationen; vi laddar bara upp PNG


def load_pod_config(config_dir: Path | str) -> dict:
    path = Path(config_dir) / "pod.toml"
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    if data.get("config_version") != 1:
        raise ValueError("pod.toml: config_version ska vara 1")
    return data


class PrintifyClient:
    """Bara HTTP. Behörighet och regler ligger i `PrintifyReader` och `PrintifyDrafter`."""

    def __init__(self, token: str, transport: Transport = urllib_transport, **kwargs) -> None:
        if not token:
            raise ApiError(f"{TOKEN_ENV} saknas")
        kwargs.setdefault("min_interval", 0.65)  # under 100 katalogeanrop per minut
        self._http = JsonClient(BASE_URL, {"Authorization": f"Bearer {token}"}, transport=transport, **kwargs)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] = os.environ, **kwargs) -> "PrintifyClient":
        return cls(environ.get(TOKEN_ENV, ""), **kwargs)

    def __repr__(self) -> str:
        return "PrintifyClient()"

    @property
    def calls(self) -> int:
        return self._http.calls

    def get(self, path: str, params=None):
        return self._http.get(path, params)

    def post(self, path: str, payload):
        if "publish" in path:
            raise ValueError("den här klienten publicerar aldrig; bara PrintifyPublisher gör det (D-070)")
        return self._http.post(path, payload)

    def put(self, path: str, payload):
        if "publish" in path:
            raise ValueError("den här klienten publicerar aldrig; bara PrintifyPublisher gör det (D-070)")
        return self._http.put(path, payload)


class PrintifyReader:
    """`printify.read`: varje metod kontrollerar verktyget före anropet och loggar utan nyckel."""

    def __init__(self, engine, audit, agent_id: str, client: PrintifyClient) -> None:
        self._engine, self._audit, self._agent, self._client = engine, audit, agent_id, client

    def _get(self, path: str, params=None):
        self._engine.require(self._agent, READ)
        data = self._client.get(path, params)
        self._audit.append(self._agent, "printify.read", {"path": path, "items": _count(data)})
        return data

    def shops(self) -> list[dict]:
        return self._get("/v1/shops.json")

    def blueprints(self) -> list[dict]:
        return self._get("/v1/catalog/blueprints.json")

    def blueprint(self, blueprint_id: int) -> dict:
        return self._get(f"/v1/catalog/blueprints/{int(blueprint_id)}.json")

    def providers(self, blueprint_id: int) -> list[dict]:
        return self._get(f"/v1/catalog/blueprints/{int(blueprint_id)}/print_providers.json")

    def variants(self, blueprint_id: int, provider_id: int) -> list[dict]:
        data = self._get(f"/v1/catalog/blueprints/{int(blueprint_id)}/print_providers/{int(provider_id)}/variants.json")
        return data.get("variants", []) if isinstance(data, dict) else data

    def shipping(self, blueprint_id: int, provider_id: int, method: str = "standard") -> list[dict]:
        if method not in ("standard", "priority", "express", "economy"):
            raise ValueError(f"okänt fraktsätt {method!r}")
        data = self._get(f"/v2/catalog/blueprints/{int(blueprint_id)}/print_providers/{int(provider_id)}"
                         f"/shipping/{method}.json")
        return parse_shipping(data)

    def orders(self, shop_id: int, page: int = 1) -> list[dict]:
        """Butikens ordrar, nyast först (en sida). Grunden för `pod orders`."""
        data = self._get(f"/v1/shops/{int(shop_id)}/orders.json", {"page": int(page), "limit": 10})
        return data.get("data", []) if isinstance(data, dict) else data

    def products(self, shop_id: int) -> list[dict]:
        """Butikens produkter. Bara här finns varianternas `cost` (baspris i cent)."""
        data = self._get(f"/v1/shops/{int(shop_id)}/products.json", {"limit": 50})
        return data.get("data", []) if isinstance(data, dict) else data

    def snapshot(self, blueprint_id: int, provider_id: int, countries) -> dict:
        """Varianter och standardfrakt per land för en produkt. Grunden för kalkylen (D-066)."""
        variants = self.variants(blueprint_id, provider_id)
        rates = self.shipping(blueprint_id, provider_id)
        by_country = {}
        for country in countries:
            rows = [r for r in rates if r["country"] == country] or [r for r in rates if r["country"] == "REST_OF_THE_WORLD"]
            if rows:
                first = [r["first_item_minor"] for r in rows if r["first_item_minor"] is not None]
                by_country[country] = {"first_item_minor_max": max(first) if first else None,
                                       "currency": rows[0]["currency"],
                                       "handling_days": rows[0]["handling_days"],
                                       "fallback": rows[0]["country"] == "REST_OF_THE_WORLD"}
        return {"blueprint_id": blueprint_id, "provider_id": provider_id,
                "variants": [{"id": v.get("id"), "title": v.get("title"), "cost_minor": v.get("cost")}
                             for v in variants if isinstance(v, dict)],
                "shipping_standard": by_country}


class PrintifyDrafter:
    """`printify.draft`: opublicerade produkter. Avstängt tills `draft_enabled = true` (D-069)."""

    def __init__(self, engine, audit, agent_id: str, client: PrintifyClient, config: dict, rules=None) -> None:
        self._engine, self._audit, self._agent, self._client = engine, audit, agent_id, client
        self._enabled = bool(config.get("printify", {}).get("draft_enabled", False))
        self._rules = rules

    def _require(self) -> None:
        if not self._enabled:
            raise PermissionError("printify.draft är avstängt i config/pod.toml tills D-069 är godkänt")
        self._engine.require(self._agent, DRAFT)

    def upload_image(self, file_name: str, url: str) -> dict:
        self._require()
        if not file_name.lower().endswith((".png", ".jpg", ".jpeg")):
            raise ValueError("Printify tar bara PNG och JPEG")
        data = self._client.post("/v1/uploads/images.json", {"file_name": file_name, "url": url})
        self._audit.append(self._agent, "printify.upload", {"file_name": file_name, "id": data.get("id")})
        return data

    def upload_image_base64(self, file_name: str, contents_b64: str) -> dict:
        """Uppladdning med base64 (Printify rekommenderar URL över 5 MB; våra PNG:er är mindre)."""
        self._require()
        if not file_name.lower().endswith(".png"):
            raise ValueError("bara PNG laddas upp härifrån")
        if len(contents_b64) * 3 // 4 > 5_000_000:
            raise ValueError("filen är över 5 MB; ladda upp med URL i stället")
        data = self._client.post("/v1/uploads/images.json", {"file_name": file_name, "contents": contents_b64})
        self._audit.append(self._agent, "printify.upload", {"file_name": file_name, "id": data.get("id")})
        return data

    def get_product(self, shop_id: int, product_id: str) -> dict:
        self._require()
        return self._client.get(f"/v1/shops/{int(shop_id)}/products/{_pid(product_id)}.json")

    def set_price(self, shop_id: int, product_id: str, variants: list[dict]) -> dict:
        """Sätter priset på en opublicerad produkt (varianternas `price` i cent)."""
        self._require()
        data = self._client.put(f"/v1/shops/{int(shop_id)}/products/{_pid(product_id)}.json", {"variants": variants})
        self._audit.append(self._agent, "printify.price", {"id": product_id, "variants": len(variants)})
        return data

    def create_draft(self, shop_id: int, product: dict) -> dict:
        """Skapar en produkt i Printify utan att publicera den. Titel och beskrivning prövas mot reglerna."""
        self._require()
        if self._rules is not None:
            problems = self._rules(product)
            if problems:
                raise ValueError("produkten stoppas: " + "; ".join(problems))
        data = self._client.post(f"/v1/shops/{int(shop_id)}/products.json", product)
        self._audit.append(self._agent, "printify.draft", {"shop_id": int(shop_id), "id": data.get("id"),
                                                           "title": product.get("title", "")[:80]})
        return data


class PrintifyPublisher:
    """`printify.publish` (D-070): publicerar en färdig produkt i Printify, som skickar den till den kopplade
    Etsy-butiken. Det är den enda vägen till publicering. Testlägets gränser kontrolleras av `aie.pod.launch.publish`
    innan den här anropas."""

    BODY = {"title": True, "description": True, "images": True, "variants": True, "tags": True,
            "keyFeatures": True, "shipping_template": True}

    def __init__(self, engine, audit, agent_id: str, client: PrintifyClient, shop_id: int) -> None:
        self._engine, self._audit, self._agent, self._client, self._shop = engine, audit, agent_id, client, int(shop_id)

    def __call__(self, product_id: str) -> dict:
        self._engine.require(self._agent, PUBLISH)
        data = self._client._http.post(f"/v1/shops/{self._shop}/products/{_pid(product_id)}/publish.json", self.BODY)
        self._audit.append(self._agent, "printify.publish", {"shop_id": self._shop, "id": product_id})
        return data


def _pid(product_id: str) -> str:
    text = str(product_id)
    if not text.isalnum():
        raise ValueError(f"ogiltigt produkt-id {product_id!r}")
    return text


def parse_shipping(data) -> list[dict]:
    """Normaliserar v2-frakt (JSON:API med `data[].attributes`, eller en enkel lista) till rader per land."""
    items = data.get("data", []) if isinstance(data, dict) else (data or [])
    rows = []
    for item in items:
        a = item.get("attributes", item) if isinstance(item, dict) else {}
        cost = (a.get("shippingCost") or {}).get("firstItem") or {}
        handling = a.get("handlingTime") or {}
        country = a.get("country") or {}
        rows.append({"variant_id": a.get("variantId"),
                     "country": country.get("code") if isinstance(country, dict) else country,
                     "first_item_minor": cost.get("amount"), "currency": cost.get("currency"),
                     "handling_days": (handling.get("from"), handling.get("to"))})
    return rows


def _count(data) -> int:
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        for key in ("data", "variants"):
            if isinstance(data.get(key), list):
                return len(data[key])
        return 1
    return 0
