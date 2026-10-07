"""Сквозной тест API с подменёнными Claude и InSales."""
import time
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app.claude_parser import ImagePick, ProductDraft
from app.config import BusinessConfig, CatalogEntry, Settings
from app.insales import InsalesClient
from app.main import Services, create_app, match_entry
from app.telegram_auth import sign_init_data

TOKEN = "1:T"


class FakeParser:
    def __init__(self):
        self.calls = []

    def build_draft(self, photos, note, purchase_price):
        self.calls.append(("build", len(photos), note, purchase_price))
        return ProductDraft(title="Футболка хлопок", description_html="<p>Хлопок.</p>", category="одежда",
                            collections=["Новинки", "Нет такой"], image_search_query="футболка", purchase_price_from_note=350, uncertainties="")

    def revise_draft(self, photos, previous, correction):
        self.calls.append(("revise", correction))
        return previous.model_copy(update={"title": "Футболка детская"})

    def pick_matching_images(self, user_photos, candidates, max_selected):
        return ImagePick(selected_indices=[1], reason="ok")


@pytest.fixture
def client(tmp_path, jpeg_bytes):
    settings = Settings(telegram_bot_token=TOKEN, allowed_telegram_user_ids="42", data_dir=tmp_path, insales_shop="s.myinsales.ru",
                        insales_api_key="k", insales_api_password="p", insales_dry_run=False, anthropic_api_key="x",
                        _env_file=None)
    cfg = BusinessConfig.model_validate({
        "catalog": {"categories": [{"id": 5, "title": "Одежда"}], "collections": [{"id": 7, "title": "Новинки"}]},
        "pricing": {"rules": [{"markup": 2}], "round_up_to": 10},
        "description": {"footer_html": "<p>Доставка по РФ.</p>"},
    })
    svc = Services(settings, cfg)
    svc.parser = FakeParser()
    insales_calls = []

    def handler(req: httpx.Request):
        insales_calls.append((req.method, req.url.path))
        if req.url.path == "/admin/products.json":
            return httpx.Response(201, json={"id": 100})
        return httpx.Response(201, json={"id": 1})

    svc.insales = InsalesClient("s.myinsales.ru", "k", "p", transport=httpx.MockTransport(handler))
    app = create_app(svc)
    c = TestClient(app)
    c.insales_calls = insales_calls
    c.svc = svc
    c.headers["X-Telegram-Init-Data"] = sign_init_data(
        {"auth_date": str(int(time.time())), "user": '{"id":42,"first_name":"V"}'}, TOKEN)
    return c


def test_match_entry():
    entries = [CatalogEntry(id=1, title="Одежда"), CatalogEntry(id=2, title="Обувь")]
    assert match_entry("одежда", entries).id == 1
    assert match_entry("Одежды", entries).id == 1
    assert match_entry("Посуда", entries) is None


def test_auth_required(client):
    assert client.get("/api/meta", headers={"X-Telegram-Init-Data": ""}).status_code == 401
    other = sign_init_data({"auth_date": str(int(time.time())), "user": '{"id":1}'}, TOKEN)
    assert client.get("/api/meta", headers={"X-Telegram-Init-Data": other}).status_code == 403
    assert client.get("/api/meta").status_code == 200


def test_full_flow(client, jpeg_bytes):
    r = client.post("/api/drafts", files=[("photos", ("a.jpg", jpeg_bytes, "image/jpeg"))], data={"note": "футболка", "purchase_price": "0"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["title"] == "Футболка хлопок"
    assert d["category_id"] == 5 and d["collections"] == ["Новинки"] and d["collection_ids"] == [7]
    assert d["purchase_price"] == 350 and d["retail_price"] == 700  # цена взята из заметки, наценка 2
    assert d["sku"].startswith("MKT-") and d["sku"].endswith("-001")
    assert len(d["images"]) == 1 and d["images"][0]["kind"] == "own"

    img = client.get(f"/api/drafts/{d['id']}/images/{d['images'][0]['id']}")
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg"

    r = client.patch(f"/api/drafts/{d['id']}", json={"purchase_price": 400, "quantity": 3})
    assert r.json()["retail_price"] == 800 and r.json()["quantity"] == 3

    r = client.post(f"/api/drafts/{d['id']}/revise", json={"correction": "детская"})
    assert r.json()["title"] == "Футболка детская"

    r = client.post(f"/api/drafts/{d['id']}/publish")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "published" and r.json()["product_id"] == 100
    assert client.insales_calls == [("POST", "/admin/products.json"), ("POST", "/admin/products/100/images.json"), ("POST", "/admin/collects.json")]

    # второй товар за день получает следующий номер
    r = client.post("/api/drafts", files=[("photos", ("b.jpg", jpeg_bytes, "image/jpeg"))], data={"note": "", "purchase_price": "100"})
    assert r.json()["sku"].endswith("-002")


def test_publish_validation(client, jpeg_bytes):
    r = client.post("/api/drafts", files=[("photos", ("a.jpg", jpeg_bytes, "image/jpeg"))], data={"purchase_price": "100"})
    d = r.json()
    client.patch(f"/api/drafts/{d['id']}", json={"title": ""})
    assert client.post(f"/api/drafts/{d['id']}/publish").status_code == 400
    client.patch(f"/api/drafts/{d['id']}", json={"title": "ok", "images": [dict(d["images"][0], selected=False)]})
    r = client.post(f"/api/drafts/{d['id']}/publish")
    assert r.status_code == 400 and "фото" in r.json()["detail"]
