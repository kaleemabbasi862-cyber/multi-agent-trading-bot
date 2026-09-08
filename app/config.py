import os
from pathlib import Path
from dotenv import load_dotenv

# Base Directory
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables
load_dotenv(BASE_DIR / ".env")

class Settings:
    PROJECT_NAME: str = "TradeTalk AI V2"
    VERSION: str = "2.0.0"
    
    # Execution & Trading Modes: 'PAPER', 'DEMO', 'LIVE'
    TRADING_MODE: str = os.getenv("TRADING_MODE", "LIVE").upper()
    
    # Target Instrument Defaults (Strictly Gold XAUUSD)
    DEFAULT_SYMBOL: str = os.getenv("DEFAULT_SYMBOL", "XAUUSD")
    DEFAULT_LOT_SIZE: float = float(os.getenv("DEFAULT_LOT_SIZE", "0.01"))
    MIN_RR_RATIO: float = float(os.getenv("MIN_RR_RATIO", "2.0"))
    MAX_OPEN_POSITIONS: int = int(os.getenv("MAX_OPEN_POSITIONS", "1"))
    
    # Risk & Capital Protection Parameters
    MAX_ACCOUNT_RISK_PERCENT: float = float(os.getenv("MAX_ACCOUNT_RISK_PERCENT", "1.0"))
    DAILY_LOSS_LIMIT: float = float(os.getenv("DAILY_LOSS_LIMIT", "5.0"))
    MAX_CONSECUTIVE_LOSSES: int = int(os.getenv("MAX_CONSECUTIVE_LOSSES", "3"))
    MAX_WEEKLY_DRAWDOWN_PERCENT: float = float(os.getenv("MAX_WEEKLY_DRAWDOWN_PERCENT", "5.0"))
    MAX_MONTHLY_DRAWDOWN_PERCENT: float = float(os.getenv("MAX_MONTHLY_DRAWDOWN_PERCENT", "10.0"))
    
    # Stop Loss & Take Profit Defaults
    MIN_SL_SPREAD_MULTIPLIER: float = float(os.getenv("MIN_SL_SPREAD_MULTIPLIER", "4.0"))
    MIN_SL_BUFFER_GOLD: float = float(os.getenv("MIN_SL_BUFFER_GOLD", "2.50")) # Mandatory $2.50 (25 pips) breathing room on Gold
    DEFAULT_SL_PIPS: float = float(os.getenv("DEFAULT_SL_PIPS", "60.0")) # $6.00 on Gold
    DEFAULT_TP_PIPS: float = float(os.getenv("DEFAULT_TP_PIPS", "120.0")) # $12.00 on Gold (1:2 R:R)
    AUTO_BREAK_EVEN_TRIGGER_PIPS: float = float(os.getenv("AUTO_BREAK_EVEN_TRIGGER_PIPS", "0.0")) # Disabled aggressive break-even
    BREAK_EVEN_BUFFER_PIPS: float = float(os.getenv("BREAK_EVEN_BUFFER_PIPS", "0.0"))
    
    # Trade Pacing & Anti-Churn Guards
    EXECUTION_COOLDOWN_SECONDS: int = int(os.getenv("EXECUTION_COOLDOWN_SECONDS", "900")) # 15 minutes between trades
    MIN_TRADE_HOLD_SECONDS: int = int(os.getenv("MIN_TRADE_HOLD_SECONDS", "300")) # 5 minutes minimum hold time
    
    # Trailing Stop Configuration: 'DISABLED', 'ATR_TRAILING', 'STRUCTURE_TRAILING', 'SWING_TRAILING'
    TRAILING_STOP_MODE: str = os.getenv("TRAILING_STOP_MODE", "DISABLED").upper()
    
    # Multi-Agent Scoring Thresholds
    MIN_DECISION_SCORE: float = float(os.getenv("MIN_DECISION_SCORE", "75.0"))
    HIGH_QUALITY_SCORE: float = float(os.getenv("HIGH_QUALITY_SCORE", "90.0"))
    
    # News & Macro Risk Windows
    NEWS_PRE_BLOCK_MINUTES: int = int(os.getenv("NEWS_PRE_BLOCK_MINUTES", "30"))
    NEWS_POST_COOLDOWN_MINUTES: int = int(os.getenv("NEWS_POST_COOLDOWN_MINUTES", "15"))
    
    # Market Data Constraints
    MAX_MARKET_DATA_AGE_SECONDS: int = int(os.getenv("MAX_MARKET_DATA_AGE_SECONDS", "30"))
    MAX_ALLOWED_SPREAD_XAUUSD: float = float(os.getenv("MAX_ALLOWED_SPREAD_XAUUSD", "1.50"))
    
    # Webhook Security
    WEBHOOK_SECRET_KEY: str = os.getenv("WEBHOOK_SECRET_KEY", "tradetalk_v2_secret_key_884920")
    REQUIRE_WEBHOOK_SIGNATURE: bool = os.getenv("REQUIRE_WEBHOOK_SIGNATURE", "false").lower() == "true"
    
    # Database
    DATABASE_PATH: str = str(BASE_DIR / "tradetalk_v2.db")
    
    # API Keys
    GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or ""
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    
    # cTrader Credentials
    CTRADER_CLIENT_ID: str = os.getenv("CTRADER_CLIENT_ID", "")
    CTRADER_CLIENT_SECRET: str = os.getenv("CTRADER_CLIENT_SECRET", "")
    CTRADER_ACCOUNT_ID: str = os.getenv("CTRADER_ACCOUNT_ID", "5908018")
    CTRADER_ENVIRONMENT: str = os.getenv("CTRADER_ENVIRONMENT", "live")
    CBOT_AUTH_TOKEN: str = os.getenv("CBOT_AUTH_TOKEN", "cbot_token_secure_9918")

settings = Settings()
