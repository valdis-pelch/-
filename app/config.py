"""Настройки: секреты из .env / переменных окружения, бизнес-правила из config.yaml."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    telegram_bot_token: str = ""
    allowed_telegram_user_ids: str = ""
    public_base_url: str = ""

    insales_shop: str = ""
    insales_api_key: str = ""
    insales_api_password: str = ""
    insales_dry_run: bool = True

    anthropic_api_key: str = ""
    claude_model: str = "claude-opus-5-5"

    image_search_provider: Literal["none", "google", "serpapi"] = "none"
    google_cse_api_key: str = ""
    google_cse_cx: str = ""
    serpapi_api_key: str = ""

    allow_unauthenticated: bool = False
    data_dir: Path = ROOT / "data"
    config_path: Path = ROOT / "config.yaml"

    @property
    def allowed_user_ids(self) -> set[int]:
        return {int(x) for x in self.allowed_telegram_user_ids.replace(";", ",").split(",") if x.strip()}


class PricingRule(BaseModel):
    max_purchase: float | None = None
    markup: float


class PricingConfig(BaseModel):
    rules: list[PricingRule] = Field(default_factory=lambda: [PricingRule(markup=2.0)])
    min_margin: float = 0
    round_up_to: float = 1
    old_price_factor: float = 0


class ShopConfig(BaseModel):
    sku_prefix: str = "MKT"
    create_hidden: bool = True
    default_quantity: int = 1
    always_add_to_collections: list[int] = Field(default_factory=list)


class CatalogEntry(BaseModel):
    id: int
    title: str
    parent_id: int | None = None


class CatalogConfig(BaseModel):
    categories: list[CatalogEntry] = Field(default_factory=list)
    collections: list[CatalogEntry] = Field(default_factory=list)


class DescriptionConfig(BaseModel):
    style: str = ""
    footer_html: str = ""
    title_max_chars: int = 80


class ImageSearchConfig(BaseModel):
    candidates: int = 8
    max_selected: int = 3
    web_first: bool = True


class BusinessConfig(BaseModel):
    shop: ShopConfig = Field(default_factory=ShopConfig)
    pricing: PricingConfig = Field(default_factory=PricingConfig)
    catalog: CatalogConfig = Field(default_factory=CatalogConfig)
    description: DescriptionConfig = Field(default_factory=DescriptionConfig)
    image_search: ImageSearchConfig = Field(default_factory=ImageSearchConfig)


def load_business_config(path: Path) -> BusinessConfig:
    if not path.exists():
        return BusinessConfig()
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return BusinessConfig.model_validate(raw)


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_business_config() -> BusinessConfig:
    return load_business_config(get_settings().config_path)
