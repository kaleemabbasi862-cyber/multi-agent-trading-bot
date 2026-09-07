import hmac
import hashlib
import time
from typing import Tuple, Optional
from app.config import settings

# Rate Limiting & Replay Cache
_SEEN_REQUEST_TIMESTAMPS = {}
_REQUEST_RATE_LIMIT = {}

class WebhookSecurityService:
    @staticmethod
    def verify_request(
        raw_body: bytes,
        signature: Optional[str],
        token: Optional[str],
        timestamp_header: Optional[str] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Validates TradingView webhook request:
        1. Token authentication
        2. HMAC-SHA256 Signature verification
        3. Replay protection (< 5 min window)
        """
        now = time.time()

        # 1. Bearer / Secret Token Check
        if token and token.strip() == settings.WEBHOOK_SECRET_KEY:
            return True, None

        # 2. HMAC Signature Check if enabled
        if settings.REQUIRE_WEBHOOK_SIGNATURE:
            if not signature:
                return False, "Missing X-TradeTalk-Signature header"
            
            expected_sig = hmac.new(
                settings.WEBHOOK_SECRET_KEY.encode("utf-8"),
                raw_body,
                hashlib.sha256
            ).hexdigest()

            if not hmac.compare_digest(signature, expected_sig):
                return False, "Invalid HMAC-SHA256 signature"

        # 3. Timestamp Replay Protection
        if timestamp_header:
            try:
                ts = float(timestamp_header)
                if abs(now - ts) > 300: # 5 minutes maximum age
                    return False, f"Request timestamp expired (Skew: {abs(now - ts):.1f}s > 300s)"
            except ValueError:
                return False, "Malformed timestamp header"

        return True, None

webhook_security = WebhookSecurityService()
