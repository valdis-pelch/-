"""Розничная цена из закупочной по правилам из config.yaml."""
from __future__ import annotations

import math

from .config import PricingConfig


def compute_retail(purchase_price: float, cfg: PricingConfig) -> float:
    if purchase_price < 0:
        raise ValueError("purchase_price must be >= 0")
    markup = None
    for rule in cfg.rules:
        if rule.max_purchase is None or purchase_price <= rule.max_purchase:
            markup = rule.markup
            break
    if markup is None:
        markup = cfg.rules[-1].markup if cfg.rules else 2.0
    retail = purchase_price * markup
    retail = max(retail, purchase_price + cfg.min_margin)
    step = cfg.round_up_to or 1
    retail = math.ceil(retail / step - 1e-9) * step
    return float(round(retail, 2))


def compute_old_price(retail: float, cfg: PricingConfig) -> float | None:
    if cfg.old_price_factor and cfg.old_price_factor > 1:
        step = cfg.round_up_to or 1
        return float(math.ceil(retail * cfg.old_price_factor / step) * step)
    return None
