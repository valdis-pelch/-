"""FastAPI-бэкенд Telegram Mini App «Карточка с рынка»."""

import difflib
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .claude_parser import ClaudeParser, ProductDraft
from .config import BusinessConfig, CatalogEntry, Settings, get_business_config, get_settings
from .drafts import Draft, DraftImage, DraftStore
from .image_search import ImageSearch
from .images import MAX_SIDE_FOR_SHOP, normalize_jpeg
from .insales import InsalesClient, InsalesError, ProductPayload
from .pricing import compute_old_price, compute_retail
from .telegram_auth import TelegramAuthError, TelegramUser, validate_init_data

log = logging.getLogger("app")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

WEBAPP_DIR = Path(__file__).resolve().parent.parent / "webapp"
MAX_PHOTOS = 6


# ---------- сборка зависимостей ----------
class Services:
    def __init__(self, settings: Settings, cfg: BusinessConfig):
        self.settings = settings
        self.cfg = cfg
        self.store = DraftStore(settings.data_dir / "drafts")
        self.parser = ClaudeParser(settings.claude_model, cfg) if settings.anthropic_api_key else None
        self.insales = (
            InsalesClient(settings.insales_shop, settings.insales_api_key, settings.insales_api_password, dry_run=settings.insales_dry_run)
            if settings.insales_shop and settings.insales_api_key
            else None
        )
        self.image_search = ImageSearch(
            settings.image_search_provider,
            google_key=settings.google_cse_api_key,
            google_cx=settings.google_cse_cx,
            serpapi_key=settings.serpapi_api_key,
        )
        self.categories: list[CatalogEntry] = list(cfg.catalog.categories)
        self.collections: list[CatalogEntry] = list(cfg.catalog.collections)

    def load_catalog_from_insales(self) -> None:
        """Если в config.yaml списки пустые, берём их из магазина (только чтение)."""
        if not self.insales:
            return
        try:
            if not self.categories:
                self.categories = [CatalogEntry(id=c["id"], title=c["title"], parent_id=c.get("parent_id")) for c in self.insales.list_categories()]
            if not self.collections:
                self.collections = [CatalogEntry(id=c["id"], title=c["title"], parent_id=c.get("parent_id")) for c in self.insales.list_collections()]
            self.cfg.catalog.categories = self.categories
            self.cfg.catalog.collections = self.collections
            log.info("catalog loaded: %d categories, %d collections", len(self.categories), len(self.collections))
        except Exception as e:
            log.warning("could not load catalog from InSales: %s", e)


def match_entry(title: str, entries: list[CatalogEntry]) -> CatalogEntry | None:
    if not title:
        return None
    by_title = {e.title.strip().lower(): e for e in entries}
    hit = by_title.get(title.strip().lower())
    if hit:
        return hit
    close = difflib.get_close_matches(title.strip().lower(), list(by_title), n=1, cutoff=0.75)
    return by_title[close[0]] if close else None


def create_app(services: Services | None = None) -> FastAPI:
    svc = services or Services(get_settings(), get_business_config())

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await run_in_threadpool(svc.load_catalog_from_insales)
        yield

    app = FastAPI(title="InSales market card", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.svc = svc

    # ---------- auth ----------
    def current_user(
        x_telegram_init_data: Annotated[str, Header()] = "",
    ) -> TelegramUser:
        s = svc.settings
        if not x_telegram_init_data and s.allow_unauthenticated:
            return TelegramUser(id=0, first_name="dev")
        try:
            user = validate_init_data(x_telegram_init_data, s.telegram_bot_token)
        except TelegramAuthError as e:
            raise HTTPException(401, f"Telegram auth failed: {e}")
        if s.allowed_user_ids and user.id not in s.allowed_user_ids:
            raise HTTPException(403, "Этот пользователь не в списке ALLOWED_TELEGRAM_USER_IDS")
        return user

    User = Annotated[TelegramUser, Depends(current_user)]

    # ---------- статика ----------
    @app.get("/")
    def index():
        return FileResponse(WEBAPP_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=WEBAPP_DIR), name="static")

    # ---------- API ----------
    @app.get("/api/health")
    def health():
        return {
            "ok": True,
            "claude": svc.parser is not None,
            "insales": svc.insales is not None,
            "insales_dry_run": svc.settings.insales_dry_run,
            "image_search": svc.image_search.enabled,
        }

    @app.get("/api/meta")
    def meta(user: User):
        return {
            "categories": [e.model_dump() for e in svc.categories],
            "collections": [e.model_dump() for e in svc.collections],
            "image_search": svc.image_search.enabled,
            "dry_run": svc.settings.insales_dry_run,
            "create_hidden": svc.cfg.shop.create_hidden,
        }

    def _get_draft(draft_id: str, user: TelegramUser) -> Draft:
        d = svc.store.load(draft_id)
        if not d or (user.id and d.user_id != user.id):
            raise HTTPException(404, "Черновик не найден")
        return d

    def _own_photos(d: Draft) -> list[bytes]:
        return [b for i in d.images if i.kind == "own" and (b := svc.store.image_bytes(d.id, i.id))]

    def _apply_parsed(d: Draft, p: ProductDraft) -> None:
        d.title = p.title.strip()[: svc.cfg.description.title_max_chars]
        d.description_html = p.description_html.strip()
        d.image_search_query = p.image_search_query.strip()
        d.uncertainties = p.uncertainties.strip()
        cat = match_entry(p.category, svc.categories)
        d.category, d.category_id = (cat.title, cat.id) if cat else (p.category, None)
        d.collections, d.collection_ids = [], []
        for c in p.collections:
            hit = match_entry(c, svc.collections)
            if hit and hit.id not in d.collection_ids:
                d.collections.append(hit.title)
                d.collection_ids.append(hit.id)
        if not d.purchase_price and p.purchase_price_from_note > 0:
            d.purchase_price = p.purchase_price_from_note
        if d.purchase_price:
            d.retail_price = compute_retail(d.purchase_price, svc.cfg.pricing)
            d.old_price = compute_old_price(d.retail_price, svc.cfg.pricing)

    def _search_web_images(d: Draft) -> None:
        if not svc.image_search.enabled or not d.image_search_query or not svc.parser:
            return
        ic = svc.cfg.image_search
        candidates = svc.image_search.search(d.image_search_query, ic.candidates)
        thumbs: list[tuple[bytes, str]] = []
        for c in candidates:
            data = svc.image_search.download(c.thumbnail_url or c.url)
            if data:
                thumbs.append((data, c.url))
        if not thumbs:
            return
        pick = svc.parser.pick_matching_images(_own_photos(d), [t[0] for t in thumbs], ic.max_selected)
        for idx in pick.selected_indices[: ic.max_selected]:
            if 1 <= idx <= len(thumbs):
                thumb, url = thumbs[idx - 1]
                full = svc.image_search.download(url) or thumb
                try:
                    full = normalize_jpeg(full, MAX_SIDE_FOR_SHOP)
                except Exception:
                    continue
                d.images.append(svc.store.put_image(d.id, full, "web", source_url=url))

    @app.post("/api/drafts")
    async def create_draft(
        user: User,
        photos: Annotated[list[UploadFile], File()],
        note: Annotated[str, Form()] = "",
        purchase_price: Annotated[float, Form()] = 0,
    ):
        if not svc.parser:
            raise HTTPException(500, "ANTHROPIC_API_KEY не задан")
        if not photos:
            raise HTTPException(400, "Нужно хотя бы одно фото")
        d = Draft(id=svc.store.new_id(), user_id=user.id, created_at=datetime.now(timezone.utc).isoformat(),
                  note=note, purchase_price=purchase_price, quantity=svc.cfg.shop.default_quantity)
        own: list[bytes] = []
        for up in photos[:MAX_PHOTOS]:
            raw = await up.read()
            try:
                jpeg = normalize_jpeg(raw, MAX_SIDE_FOR_SHOP)
            except Exception:
                raise HTTPException(400, f"Файл {up.filename} не похож на изображение")
            own.append(jpeg)
            d.images.append(svc.store.put_image(d.id, jpeg, "own"))
        try:
            parsed = await run_in_threadpool(svc.parser.build_draft, own, note, purchase_price or None)
        except Exception as e:
            log.exception("claude failed")
            svc.store.delete(d.id)
            raise HTTPException(502, f"Claude: {e}")
        _apply_parsed(d, parsed)
        d.sku = svc.store.next_sku(svc.cfg.shop.sku_prefix)
        await run_in_threadpool(_search_web_images, d)
        if svc.cfg.image_search.web_first:
            d.images.sort(key=lambda i: 0 if i.kind == "web" else 1)
        svc.store.save(d)
        return d

    class Revise(BaseModel):
        correction: str

    @app.post("/api/drafts/{draft_id}/revise")
    async def revise(draft_id: str, body: Revise, user: User):
        d = _get_draft(draft_id, user)
        if not svc.parser:
            raise HTTPException(500, "ANTHROPIC_API_KEY не задан")
        previous = ProductDraft(
            title=d.title, description_html=d.description_html, category=d.category, collections=d.collections,
            image_search_query=d.image_search_query, purchase_price_from_note=d.purchase_price, uncertainties=d.uncertainties,
        )
        try:
            parsed = await run_in_threadpool(svc.parser.revise_draft, _own_photos(d), previous, body.correction)
        except Exception as e:
            raise HTTPException(502, f"Claude: {e}")
        old_query = d.image_search_query
        _apply_parsed(d, parsed)
        if d.image_search_query != old_query and not any(i.kind == "web" for i in d.images):
            await run_in_threadpool(_search_web_images, d)
        svc.store.save(d)
        return d

    class Patch(BaseModel):
        title: str | None = None
        description_html: str | None = None
        category_id: int | None = None
        collection_ids: list[int] | None = None
        purchase_price: float | None = None
        retail_price: float | None = None
        quantity: int | None = None
        images: list[DraftImage] | None = None

    @app.patch("/api/drafts/{draft_id}")
    def patch_draft(draft_id: str, body: Patch, user: User):
        d = _get_draft(draft_id, user)
        data = body.model_dump(exclude_none=True)
        if "purchase_price" in data and data["purchase_price"] != d.purchase_price:
            d.purchase_price = data.pop("purchase_price")
            d.retail_price = compute_retail(d.purchase_price, svc.cfg.pricing)
            d.old_price = compute_old_price(d.retail_price, svc.cfg.pricing)
        if "category_id" in data:
            hit = next((c for c in svc.categories if c.id == data["category_id"]), None)
            d.category = hit.title if hit else d.category
        if "collection_ids" in data:
            d.collections = [c.title for c in svc.collections if c.id in data["collection_ids"]]
        if "images" in data:
            known = {i.id for i in d.images}
            data["images"] = [DraftImage.model_validate(i) for i in data["images"] if i["id"] in known]
        for k, v in data.items():
            setattr(d, k, v)
        svc.store.save(d)
        return d

    @app.post("/api/drafts/{draft_id}/publish")
    async def publish(draft_id: str, user: User):
        d = _get_draft(draft_id, user)
        if not svc.insales:
            raise HTTPException(500, "InSales не настроен (INSALES_SHOP / INSALES_API_KEY)")
        if d.status == "published":
            return d
        if not d.title:
            raise HTTPException(400, "Пустое название")
        if not d.category_id:
            raise HTTPException(400, "Не выбрана категория")
        if d.retail_price <= 0:
            raise HTTPException(400, "Розничная цена не задана")
        images = [(b, i.id) for i in d.images if i.selected and (b := svc.store.image_bytes(d.id, i.id))]
        if not images:
            raise HTTPException(400, "Не выбрано ни одного фото")
        payload = ProductPayload(
            title=d.title,
            description_html=d.description_html + (svc.cfg.description.footer_html or ""),
            category_id=d.category_id,
            price=d.retail_price,
            old_price=d.old_price,
            sku=d.sku,
            quantity=d.quantity,
            is_hidden=svc.cfg.shop.create_hidden,
            collection_ids=sorted(set(d.collection_ids) | set(svc.cfg.shop.always_add_to_collections)),
            images=images,
        )
        try:
            created = await run_in_threadpool(svc.insales.create_product, payload)
        except InsalesError as e:
            d.status, d.error = "failed", str(e)
            svc.store.save(d)
            raise HTTPException(502, f"InSales: {e}")
        d.status = "published" if not created.dry_run else "dry_run"
        d.product_id, d.admin_url, d.error = created.id, created.admin_url, ""
        svc.store.save(d)
        return d

    @app.get("/api/drafts/{draft_id}/images/{image_id}")
    def draft_image(draft_id: str, image_id: str):
        # id черновика случайный и неугадываемый, заголовки в <img> передать нельзя.
        data = svc.store.image_bytes(draft_id, image_id)
        if data is None:
            raise HTTPException(404)
        return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})

    @app.delete("/api/drafts/{draft_id}")
    def delete_draft(draft_id: str, user: User):
        _get_draft(draft_id, user)
        svc.store.delete(draft_id)
        return {"ok": True}

    return app


app = create_app()
