from app.services.webhook_security import webhook_security
from app.config import settings

def test_webhook_security_valid_token():
    valid, err = webhook_security.verify_request(
        raw_body=b'{"symbol": "XAUUSD"}',
        signature=None,
        token=settings.WEBHOOK_SECRET_KEY
    )
    assert valid is True
    assert err is None

def test_webhook_security_invalid_token():
    settings.REQUIRE_WEBHOOK_SIGNATURE = True
    valid, err = webhook_security.verify_request(
        raw_body=b'{"symbol": "XAUUSD"}',
        signature="invalid_sig",
        token="wrong_token"
    )
    settings.REQUIRE_WEBHOOK_SIGNATURE = False
    assert valid is False
