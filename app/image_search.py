"""Поиск фото товара в интернете. Провайдер выбирается в .env (IMAGE_SEARCH_PROVIDER).

Юридическая оговорка: чужие фото могут быть защищены авторским правом. Используйте
для своих карточек фото производителя/поставщика или проверяйте источник.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)


@dataclass
class Candidate:
    url: str
    thumbnail_url: str
    source: str = ""


class ImageSearch:
    def __init__(self, provider: str, *, google_key: str = "", google_cx: str = "", serpapi_key: str = "", transport=None):
        self.provider = provider
        self.google_key, self.google_cx, self.serpapi_key = google_key, google_cx, serpapi_key
        self._client = httpx.Client(timeout=30, follow_redirects=True, transport=transport,
                                    headers={"User-Agent": "Mozilla/5.0 (insales-market-app)"})

    @property
    def enabled(self) -> bool:
        if self.provider == "google":
            return bool(self.google_key and self.google_cx)
        if self.provider == "serpapi":
            return bool(self.serpapi_key)
        return False

    def search(self, query: str, limit: int) -> list[Candidate]:
        if not self.enabled or not query.strip():
            return []
        try:
            if self.provider == "google":
                return self._google(query, limit)
            if self.provider == "serpapi":
                return self._serpapi(query, limit)
        except Exception as e:  # поиск картинок не должен ломать создание карточки
            log.warning("image search failed: %s", e)
        return []

    def _google(self, query: str, limit: int) -> list[Candidate]:
        r = self._client.get(
            "https://www.googleapis.com/customsearch/v1",
            params={"key": self.google_key, "cx": self.google_cx, "q": query, "searchType": "image",
                    "num": min(limit, 10), "imgSize": "large", "safe": "active"},
        )
        r.raise_for_status()
        out = []
        for item in r.json().get("items", []):
            thumb = (item.get("image") or {}).get("thumbnailLink", item.get("link", ""))
            out.append(Candidate(url=item["link"], thumbnail_url=thumb, source=item.get("displayLink", "")))
        return out

    def _serpapi(self, query: str, limit: int) -> list[Candidate]:
        r = self._client.get(
            "https://serpapi.com/search.json",
            params={"engine": "google_images", "q": query, "api_key": self.serpapi_key, "hl": "ru", "gl": "ru"},
        )
        r.raise_for_status()
        out = []
        for item in r.json().get("images_results", [])[:limit]:
            out.append(Candidate(url=item.get("original", ""), thumbnail_url=item.get("thumbnail", ""), source=item.get("source", "")))
        return [c for c in out if c.url]

    def download(self, url: str, max_bytes: int = 15_000_000) -> bytes | None:
        try:
            r = self._client.get(url)
            r.raise_for_status()
            if not r.headers.get("content-type", "").startswith("image/"):
                return None
            if len(r.content) > max_bytes:
                return None
            return r.content
        except Exception as e:
            log.info("download failed %s: %s", url, e)
            return None
