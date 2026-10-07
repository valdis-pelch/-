import json

import httpx
import pytest

from app.insales import InsalesClient, InsalesError, ProductPayload


def make_client(handler, dry_run=False):
    return InsalesClient("shop.myinsales.ru", "key", "pass", dry_run=dry_run, transport=httpx.MockTransport(handler))


def test_create_product_flow(jpeg_bytes):
    calls = []

    def handler(req: httpx.Request):
        calls.append((req.method, req.url.path, json.loads(req.content) if req.content else None))
        assert req.headers["Authorization"].startswith("Basic ")
        if req.url.path == "/admin/products.json":
            return httpx.Response(201, json={"id": 777, "variants": [{"id": 1}]})
        if req.url.path == "/admin/products/777/images.json":
            return httpx.Response(201, json={"id": 55})
        if req.url.path == "/admin/collects.json":
            return httpx.Response(201, json={"id": 9})
        return httpx.Response(404)

    p = ProductPayload(title="Футболка", description_html="<p>x</p>", category_id=12, price=700, sku="MKT-1",
                       old_price=910, collection_ids=[3], images=[(jpeg_bytes, "own_01.jpg")])
    created = make_client(handler).create_product(p)
    assert created.id == 777 and created.image_ids == [55]
    assert created.admin_url == "https://shop.myinsales.ru/admin2/products/777"
    methods = [(m, path) for m, path, _ in calls]
    assert methods == [("POST", "/admin/products.json"), ("POST", "/admin/products/777/images.json"), ("POST", "/admin/collects.json")]
    body = calls[0][2]["product"]
    assert body["category_id"] == 12 and body["is_hidden"] is True
    assert body["variants"][0] == {"price": 700, "sku": "MKT-1", "quantity": 1, "old_price": 910}
    assert calls[1][2]["image"]["filename"] == "own_01.jpg" and calls[1][2]["image"]["attachment"]
    assert calls[2][2] == {"collect": {"product_id": 777, "collection_id": 3}}


def test_dry_run_does_not_call():
    def handler(req):
        raise AssertionError("no HTTP in dry run")

    p = ProductPayload(title="t", description_html="", category_id=1, price=10, sku="s")
    created = make_client(handler, dry_run=True).create_product(p)
    assert created.dry_run and created.id == 0


def test_rate_limit_retry_then_error():
    n = {"c": 0}

    def handler(req):
        n["c"] += 1
        if n["c"] == 1:
            return httpx.Response(503, headers={"Retry-After": "0"})
        return httpx.Response(422, text="Validation failed")

    with pytest.raises(InsalesError, match="422"):
        make_client(handler).list_categories()
    assert n["c"] == 2
