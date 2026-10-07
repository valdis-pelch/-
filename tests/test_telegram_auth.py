import time

import pytest

from app.telegram_auth import TelegramAuthError, sign_init_data, validate_init_data

TOKEN = "123456:TEST-TOKEN"


def make(fields=None):
    base = {"auth_date": str(int(time.time())), "query_id": "AAE", "user": '{"id":42,"first_name":"Vas","username":"vas"}'}
    base.update(fields or {})
    return sign_init_data(base, TOKEN)


def test_valid():
    u = validate_init_data(make(), TOKEN)
    assert u.id == 42 and u.username == "vas"


def test_bad_signature():
    with pytest.raises(TelegramAuthError):
        validate_init_data(make() + "x", TOKEN)
    with pytest.raises(TelegramAuthError):
        validate_init_data(make(), "other-token")


def test_expired():
    with pytest.raises(TelegramAuthError):
        validate_init_data(make({"auth_date": str(int(time.time()) - 100000)}), TOKEN)
