import datetime
import logging
from typing import Dict, Any, List

logger = logging.getLogger("TradeTalk.Alerts")

class AlertService:
    def __init__(self):
        self.alert_history: List[Dict[str, Any]] = []

    def dispatch_alert(self, title: str, message: str, level: str = "INFO", category: str = "GENERAL"):
        now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S UTC")
        alert_item = {
            "title": title,
            "message": message,
            "level": level, # INFO, WARNING, CRITICAL, SUCCESS
            "category": category, # CONSENSUS, RISK, EXECUTION, SYSTEM
            "timestamp": now_str
        }
        self.alert_history.insert(0, alert_item)
        if len(self.alert_history) > 100:
            self.alert_history.pop()

        log_msg = f"[{level}] [{category}] {title}: {message}"
        if level == "CRITICAL":
            logger.critical(log_msg)
        elif level == "WARNING":
            logger.warning(log_msg)
        else:
            logger.info(log_msg)

    def get_recent_alerts(self, limit: int = 20) -> List[Dict[str, Any]]:
        return self.alert_history[:limit]

alert_service = AlertService()
