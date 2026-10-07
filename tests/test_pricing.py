from app.config import PricingConfig, PricingRule
from app.pricing import compute_old_price, compute_retail


def cfg(**kw):
    base = dict(rules=[PricingRule(max_purchase=300, markup=2.5), PricingRule(max_purchase=1000, markup=2.0), PricingRule(markup=1.5)],
                min_margin=100, round_up_to=10, old_price_factor=0)
    base.update(kw)
    return PricingConfig(**base)


def test_tiers_and_rounding():
    assert compute_retail(100, cfg()) == 250
    assert compute_retail(350, cfg()) == 700
    assert compute_retail(2000, cfg()) == 3000
    assert compute_retail(333, cfg()) == 670  # 666 -> вверх до 670


def test_min_margin():
    assert compute_retail(10, cfg()) == 110  # 25 < 10+100


def test_old_price():
    assert compute_old_price(700, cfg()) is None
    assert compute_old_price(700, cfg(old_price_factor=1.3)) == 910
