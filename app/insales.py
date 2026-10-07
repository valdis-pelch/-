"""Клиент InSales API v2 (REST, JSON).

ВНИМАНИЕ: имена полей ниже собраны по документации API v2 по памяти, т.к. при
разработке сайт api.insales.ru был недоступен. Перед первым боевым запуском
сверьте с https://api.insales.ru (разделы Product, Image, Category, Collection,
Collect). Весь контакт с InSales намеренно собран в этом файле.

Схема, на которую рассчитан код:
  GET  /admin/categories.json                 -> [{"id", "title", "parent_id", ...}]
  GET  /admin/collections.json                -> [{"id", "title", "parent_id", ...}]
  POST /admin/products.json
       {"product": {"category_id", "title", "description", "is_hidden",
                    "variants": [{"price", "old_price", "sku", "quantity"}]}}
                                              -> {"id", "variants": [...], ...}
  POST /admin/products/{id}/images.json
       {"image": {"attachment": <base64>, "filename": "x.jpg"}}   (или {"src": url})
  POST /admin/collects.json
       {"collect": {"product_id", "collection_id"}}
Авторизация: HTTP Basic (api_key : password). Лимит ~500 запросов / 5 минут,
при превышении 503 + Retry-After.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import httpx

log = logging.getLogger(__name__)


class InsalesError(Exception):
    pass


@dataclass
class ProductPayload:
    title: str
    description_html: str
    category_id: int
    price: float
    sku: str
    quantity: int = 1
    old_price: float | None = None
    is_hidden: bool = True
    collection_ids: list[int] = field(default_factory=list)
    # (bytes, filename) в нужном порядке
    images: list[tuple[bytes, str]] = field(default_factory=list)

    def product_json(self) -> dict:
        variant = {"price": self.price, "sku": self.sku, "quantity": self.quantity}
        if self.old_price:
            variant["old_price"] = self.old_price
        return {
            "product": {
                "category_id": self.category_id,
                "title": self.title,
                "description": self.description_html,
                "is_hidden": self.is_hidden,
                "variants": [variant],
            }
        }


@dataclass
class CreatedProduct:
    id: int
    admin_url: str
    image_ids: list[int] = field(default_factory=list)
    dry_run: bool = False


class InsalesClient:
    def __init__(self, shop: str, api_key: str, password: str, dry_run: bool = False, transport=None):
        self.shop = shop.replace("https://", "").replace("http://", "").strip("/")
        self.dry_run = dry_run
        self._client = httpx.Client(
            base_url=f"https://{self.shop}",
            auth=(api_key, password),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=60,
            transport=transport,
        )

    # --- низкоуровневое ---
    def _request(self, method: str, path: str, json: dict | None = None, retries: int = 3) -> httpx.Response:
        for attempt in range(retries + 1):
            resp = self._client.request(method, path, json=json)
            if resp.status_code == 503 and attempt < retries:
                wait = float(resp.headers.get("Retry-After", "5"))
                log.warning("InSales rate limit, sleeping %.0fs", wait)
                time.sleep(wait)
                continue
            if resp.status_code >= 400:
                raise InsalesError(f"{method} {path} -> {resp.status_code}: {resp.text[:500]}")
            return resp
        raise InsalesError(f"{method} {path}: too many retries")

    # --- справочники ---
    def list_categories(self) -> list[dict]:
        return self._request("GET", "/admin/categories.json").json()

    def list_collections(self) -> list[dict]:
        out: list[dict] = []
        page = 1
        while True:
            chunk = self._request("GET", f"/admin/collections.json?per_page=250&page={page}").json()
            out.extend(chunk)
            if len(chunk) < 250:
                return out
            page += 1

    # --- товары ---
    def admin_product_url(self, product_id: int) -> str:
        return f"https://{self.shop}/admin2/products/{product_id}"

    def create_product(self, p: ProductPayload) -> CreatedProduct:
        body = p.product_json()
        if self.dry_run:
            log.info("DRY RUN create_product: %s (+%d images, collections=%s)", body, len(p.images), p.collection_ids)
            return CreatedProduct(id=0, admin_url="(dry run)", dry_run=True)

        created = self._request("POST", "/admin/products.json", json=body).json()
        product_id = int(created["id"])
        result = CreatedProduct(id=product_id, admin_url=self.admin_product_url(product_id))

        from .images import to_base64

        for position, (data, filename) in enumerate(p.images, start=1):
            img = self._request(
                "POST",
                f"/admin/products/{product_id}/images.json",
                json={"image": {"attachment": to_base64(data), "filename": filename, "position": position}},
            ).json()
            if isinstance(img, dict) and "id" in img:
                result.image_ids.append(int(img["id"]))

        for collection_id in p.collection_ids:
            self._request("POST", "/admin/collects.json", json={"collect": {"product_id": product_id, "collection_id": collection_id}})
        return result
