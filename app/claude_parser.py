"""Claude: фото + заметка -> структурированная карточка товара."""
from __future__ import annotations

import json
import logging
from typing import Any

import anthropic
from pydantic import BaseModel, Field

from .config import BusinessConfig
from .images import to_claude_image_block

log = logging.getLogger(__name__)

BETAS = ["server-side-fallback-2026-07-01"]


class ProductDraft(BaseModel):
    """То, что возвращает Claude. Все поля обязательны, пустое = "" / 0 / []."""

    title: str = Field(description="Название товара для витрины, без артикула и цены")
    description_html: str = Field(description="Описание в простом HTML: <p>, <ul>, <li>, <b>")
    category: str = Field(description="Название категории строго из списка допустимых, или пустая строка")
    collections: list[str] = Field(description="Названия коллекций строго из списка допустимых, 0-3 штуки")
    image_search_query: str = Field(description="Короткий запрос для поиска фото этого товара в интернете, на русском")
    purchase_price_from_note: float = Field(description="Закупочная цена, если она указана в заметке продавца, иначе 0")
    uncertainties: str = Field(description="Что не удалось определить по фото и заметке, одной фразой, или пустая строка")


class ImagePick(BaseModel):
    selected_indices: list[int] = Field(description="Номера кандидатов (с 1), на которых тот же самый товар")
    reason: str


def _system_prompt(cfg: BusinessConfig) -> str:
    cats = "\n".join(f"- {c.title}" for c in cfg.catalog.categories) or "(список категорий не задан, оставь пустую строку)"
    cols = "\n".join(f"- {c.title}" for c in cfg.catalog.collections) or "(список коллекций не задан, верни пустой список)"
    return f"""Ты помогаешь владельцу небольшого интернет-магазина на InSales заводить карточки товаров.
Продавец ходит по оптовому рынку, фотографирует товар и пишет короткую заметку. По фото и заметке собери карточку.

Правила названия: до {cfg.description.title_max_chars} символов, с большой буквы, без кавычек-ёлочек вокруг всего названия,
без артикула и цены. Формат: тип товара + ключевые признаки (материал, цвет, размер, бренд если виден).

Правила описания:
{cfg.description.style.strip()}

Категория: выбери одну, название должно совпадать с одним из списка буквально:
{cats}

Коллекции (разделы витрины), 0-3 штуки, названия буквально из списка:
{cols}

image_search_query: запрос, по которому в картинках поисковика найдётся этот же товар (бренд, модель, тип, цвет).
Если на фото виден бренд или артикул производителя, включи их в запрос.

Не выдумывай характеристики, которых нет на фото и в заметке. Ответ строго в заданной JSON-схеме."""


class ClaudeParser:
    def __init__(self, model: str, cfg: BusinessConfig, client: anthropic.Anthropic | None = None):
        self.model = model
        self.cfg = cfg
        self.client = client or anthropic.Anthropic()

    def _call(self, output_model: type[BaseModel], system: str, content: list[dict[str, Any]], effort: str = "medium"):
        resp = self.client.beta.messages.parse(
            model=self.model,
            max_tokens=4000,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": content}],
            output_format=output_model,
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
            betas=BETAS,
            fallbacks="default",
        )
        if resp.stop_reason == "refusal":
            raise RuntimeError("Claude отказался обрабатывать запрос (refusal)")
        parsed = getattr(resp, "parsed_output", None)
        if parsed is None:
            text = next(b.text for b in resp.content if b.type == "text")
            parsed = output_model.model_validate(json.loads(text))
        return parsed

    def build_draft(self, photos: list[bytes], note: str, purchase_price: float | None) -> ProductDraft:
        content: list[dict[str, Any]] = [to_claude_image_block(p) for p in photos]
        text = f"Заметка продавца: {note.strip() or '(нет)'}\n"
        text += f"Закупочная цена: {purchase_price:g} руб.\n" if purchase_price else "Закупочная цена не указана отдельно, поищи её в заметке.\n"
        text += "Собери карточку товара по фото выше и заметке."
        content.append({"type": "text", "text": text})
        return self._call(ProductDraft, _system_prompt(self.cfg), content)

    def revise_draft(self, photos: list[bytes], previous: ProductDraft, correction: str) -> ProductDraft:
        content: list[dict[str, Any]] = [to_claude_image_block(p) for p in photos]
        content.append(
            {
                "type": "text",
                "text": (
                    "Текущая карточка (JSON):\n"
                    + previous.model_dump_json(indent=1)
                    + f"\n\nПравка продавца: {correction.strip()}\n\n"
                    "Верни исправленную карточку целиком. Меняй только то, чего касается правка."
                ),
            }
        )
        return self._call(ProductDraft, _system_prompt(self.cfg), content)

    def pick_matching_images(self, user_photos: list[bytes], candidates: list[bytes], max_selected: int) -> ImagePick:
        content: list[dict[str, Any]] = [{"type": "text", "text": "Фото товара с рынка (эталон):"}]
        content += [to_claude_image_block(p) for p in user_photos]
        for i, c in enumerate(candidates, start=1):
            content.append({"type": "text", "text": f"Кандидат {i}:"})
            content.append(to_claude_image_block(c))
        content.append(
            {
                "type": "text",
                "text": (
                    f"Выбери не больше {max_selected} кандидатов, на которых ТОТ ЖЕ товар (та же модель, цвет, форма), "
                    "и которые годятся как фото для карточки в магазине: чистый фон, без водяных знаков, без чужих ценников и логотипов магазинов. "
                    "Если ни один не подходит, верни пустой список. Лучше пропустить, чем взять похожий, но другой товар."
                ),
            }
        )
        system = "Ты сверяешь фотографии товаров для интернет-магазина. Отвечай строго по JSON-схеме."
        return self._call(ImagePick, system, content, effort="low")
