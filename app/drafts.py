"""Черновики карточек: JSON + файлы картинок на диске, data/drafts/<id>/."""
from __future__ import annotations

import json
import secrets
import shutil
from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field


class DraftImage(BaseModel):
    id: str              # имя файла в папке черновика
    kind: str            # "own" (с рынка) | "web"
    source_url: str = ""
    selected: bool = True


class Draft(BaseModel):
    id: str
    user_id: int
    created_at: str
    note: str = ""
    purchase_price: float = 0
    title: str = ""
    description_html: str = ""
    category: str = ""
    category_id: int | None = None
    collections: list[str] = Field(default_factory=list)
    collection_ids: list[int] = Field(default_factory=list)
    image_search_query: str = ""
    uncertainties: str = ""
    retail_price: float = 0
    old_price: float | None = None
    sku: str = ""
    quantity: int = 1
    images: list[DraftImage] = Field(default_factory=list)
    status: str = "draft"      # draft | published | failed
    product_id: int | None = None
    admin_url: str = ""
    error: str = ""


class DraftStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def dir(self, draft_id: str) -> Path:
        return self.root / draft_id

    def new_id(self) -> str:
        return secrets.token_urlsafe(8)

    def save(self, d: Draft) -> None:
        self.dir(d.id).mkdir(parents=True, exist_ok=True)
        (self.dir(d.id) / "draft.json").write_text(d.model_dump_json(indent=1), encoding="utf-8")

    def load(self, draft_id: str) -> Draft | None:
        p = self.dir(draft_id) / "draft.json"
        if not p.exists():
            return None
        return Draft.model_validate_json(p.read_text(encoding="utf-8"))

    def put_image(self, draft_id: str, data: bytes, kind: str, source_url: str = "") -> DraftImage:
        d = self.dir(draft_id)
        d.mkdir(parents=True, exist_ok=True)
        n = len(list(d.glob("*.jpg"))) + 1
        name = f"{kind}_{n:02d}.jpg"
        (d / name).write_bytes(data)
        return DraftImage(id=name, kind=kind, source_url=source_url)

    def image_bytes(self, draft_id: str, image_id: str) -> bytes | None:
        p = self.dir(draft_id) / Path(image_id).name
        return p.read_bytes() if p.exists() else None

    def delete(self, draft_id: str) -> None:
        shutil.rmtree(self.dir(draft_id), ignore_errors=True)

    def next_sku(self, prefix: str) -> str:
        """prefix-ГГГГММДД-NNN, счётчик за день хранится в файле."""
        today = date.today().strftime("%Y%m%d")
        counter_file = self.root / "sku_counter.json"
        state = {"day": today, "n": 0}
        if counter_file.exists():
            try:
                state = json.loads(counter_file.read_text())
            except json.JSONDecodeError:
                pass
        if state.get("day") != today:
            state = {"day": today, "n": 0}
        state["n"] = int(state.get("n", 0)) + 1
        counter_file.write_text(json.dumps(state))
        return f"{prefix}-{today}-{state['n']:03d}"
