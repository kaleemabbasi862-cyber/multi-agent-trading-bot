import os
from pathlib import Path
from dotenv import load_dotenv

# Base Directory
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables
load_dotenv(BASE_DIR / ".env")

class Settings:
    PROJECT_NAME: str = "TradeTalk AI V2"
    VERSION: str = "2.1.0-DEMO-CANDIDATE"
    
    # Execution & Trading Modes: 'PAPER', 'DEMO', 'LIVE'
    TRADING_MODE: str = os.getenv("TRADING_MODE", "DEMO").upper()
    
    # Emergency Kill Switch
    EMERGENCY_KILL_SWITCH_ACTIVE: bool = False
    
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
    RISK_DAY_TIMEZONE: str = os.getenv("RISK_DAY_TIMEZONE", "UTC")
    
    # Stop Loss & Take Profit Defaults
    MIN_SL_SPREAD_MULTIPLIER: float = float(os.getenv("MIN_SL_SPREAD_MULTIPLIER", "4.0"))
    MIN_SL_BUFFER_GOLD: float = float(os.getenv("MIN_SL_BUFFER_GOLD", "2.00")) # Mandatory min 20 pips ($2.00) SL on Gold
    MIN_TP_BUFFER_GOLD: float = float(os.getenv("MIN_TP_BUFFER_GOLD", "4.00")) # Mandatory min 40 pips ($4.00) TP on Gold
    DEFAULT_SL_PIPS: float = float(os.getenv("DEFAULT_SL_PIPS", "60.0")) # $6.00 on Gold
    DEFAULT_TP_PIPS: float = float(os.getenv("DEFAULT_TP_PIPS", "120.0")) # $12.00 on Gold (1:2 R:R)
    AUTO_BREAK_EVEN_TRIGGER_PIPS: float = float(os.getenv("AUTO_BREAK_EVEN_TRIGGER_PIPS", "0.0"))
    BREAK_EVEN_BUFFER_PIPS: float = float(os.getenv("BREAK_EVEN_BUFFER_PIPS", "0.0"))
    
    # Trade Pacing & Anti-Churn Guards
    EXECUTION_COOLDOWN_SECONDS: int = int(os.getenv("EXECUTION_COOLDOWN_SECONDS", "30")) # 30 seconds debounce between trades
    TRADE_CLOSE_COOLDOWN_SECONDS: int = int(os.getenv("TRADE_CLOSE_COOLDOWN_SECONDS", "10")) # 10 seconds debounce after trade close
    MIN_TRADE_HOLD_SECONDS: int = int(os.getenv("MIN_TRADE_HOLD_SECONDS", "60")) # 1 minute minimum hold time
    
    # Trailing Stop Configuration: 'DISABLED', 'ATR_TRAILING', 'STRUCTURE_TRAILING', 'SWING_TRAILING'
    TRAILING_STOP_MODE: str = os.getenv("TRAILING_STOP_MODE", "DISABLED").upper()
    
    # Multi-Agent Strict Consensus Thresholds (4 of 7 with >= 65% Conviction)
    MIN_CONSENSUS_AGENTS: int = int(os.getenv("MIN_CONSENSUS_AGENTS", "4"))
    MIN_AGENT_CONFIDENCE: float = float(os.getenv("MIN_AGENT_CONFIDENCE", "65.0"))
    MIN_DECISION_SCORE: float = float(os.getenv("MIN_DECISION_SCORE", "65.0"))
    HIGH_QUALITY_SCORE: float = float(os.getenv("HIGH_QUALITY_SCORE", "85.0"))
    
    # News & Macro Risk Windows
    NEWS_PRE_BLOCK_MINUTES: int = int(os.getenv("NEWS_PRE_BLOCK_MINUTES", "30"))
    NEWS_POST_COOLDOWN_MINUTES: int = int(os.getenv("NEWS_POST_COOLDOWN_MINUTES", "15"))
    
    # Market Data Constraints
    MAX_MARKET_DATA_AGE_SECONDS: int = int(os.getenv("MAX_MARKET_DATA_AGE_SECONDS", "30"))
    MAX_ALLOWED_SPREAD_XAUUSD: float = float(os.getenv("MAX_ALLOWED_SPREAD_XAUUSD", "0.55")) # Max $0.55 (55 cents) on Gold
    
    # Webhook Security
    WEBHOOK_SECRET_KEY: str = os.getenv("WEBHOOK_SECRET_KEY", "")
    REQUIRE_WEBHOOK_SIGNATURE: bool = os.getenv("REQUIRE_WEBHOOK_SIGNATURE", "false").lower() == "true"
    
    # Database
    DATABASE_PATH: str = str(BASE_DIR / "tradetalk_v2.db")
    
    # API Keys & cTrader Credentials (dynamically queried with fallback to credential store)
    @property
    def GOOGLE_API_KEY(self) -> str:
        from app.services.credential_store import credential_store
        return credential_store.get_secret("GOOGLE_API_KEY", os.getenv("GEMINI_API_KEY", ""))

    @property
    def GROQ_API_KEY(self) -> str:
        from app.services.credential_store import credential_store
        return credential_store.get_secret("GROQ_API_KEY", "")

    @property
    def CTRADER_CLIENT_ID(self) -> str:
        from app.services.credential_store import credential_store
        return credential_store.get_secret("CTRADER_CLIENT_ID", os.getenv("CTRADER_CLIENT_ID", ""))

    @property
    def CTRADER_CLIENT_SECRET(self) -> str:
        from app.services.credential_store import credential_store
        return credential_store.get_secret("CTRADER_CLIENT_SECRET", os.getenv("CTRADER_CLIENT_SECRET", ""))

    @property
    def CTRADER_ACCOUNT_ID(self) -> str:
        from app.services.credential_store import credential_store
        return credential_store.get_secret("CTRADER_ACCOUNT_ID", "5908018")

    @property
    def CTRADER_ACCESS_TOKEN(self) -> str:
        from app.services.credential_store import credential_store
        return credential_store.get_secret("CTRADER_ACCESS_TOKEN", "")

    @property
    def CTRADER_REFRESH_TOKEN(self) -> str:
        from app.services.credential_store import credential_store
        return credential_store.get_secret("CTRADER_REFRESH_TOKEN", "")

    CTRADER_ENVIRONMENT: str = os.getenv("CTRADER_ENVIRONMENT", "demo")
    CBOT_AUTH_TOKEN: str = os.getenv("CBOT_AUTH_TOKEN", "")

settings = Settings()

# ==============================================================================
# CENTRALIZED TRADING CONSTANTS & PROVENANCE REGISTRY (PHASE 2 HARDENING)
# ==============================================================================
from enum import Enum
from typing import Dict, Any, Optional
from pydantic import BaseModel

class ConstantCategory(str, Enum):
    BROKER_PROTOCOL = "A_PROTOCOL_BROKER_REQUIREMENT"
    SAFETY_POLICY = "B_SAFETY_POLICY"
    STRATEGY_CONFIG = "C_STRATEGY_CONFIGURATION"
    MARKET_DERIVED = "D_MARKET_DERIVED"
    IMPLEMENTATION = "E_IMPLEMENTATION_CONSTANT"
    PROHIBITED_MAGIC = "F_UNJUSTIFIED_MAGIC_NUMBER"

class TradingConstantDefinition(BaseModel):
    name: str
    value: Any
    unit: str
    category: ConstantCategory
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    symbol_scope: str = "GLOBAL"
    provenance_source: str
    rationale: str
    is_adaptive: bool = False

TRADING_CONSTANTS_REGISTRY: Dict[str, TradingConstantDefinition] = {
    # --- CATEGORY A: PROTOCOL / BROKER REQUIREMENTS ---
    "MIN_ORDER_VOLUME_GOLD": TradingConstantDefinition(
        name="MIN_ORDER_VOLUME_GOLD",
        value=0.01,
        unit="Lots (1 oz)",
        category=ConstantCategory.BROKER_PROTOCOL,
        min_value=0.01,
        max_value=100.0,
        symbol_scope="XAUUSD",
        provenance_source="cTrader Spotware Open API v2 Protocol Specification",
        rationale="cTrader and broker minimum order increment for Gold contracts is 0.01 lots (1 ounce)."
    ),
    "PRICE_DECIMALS_GOLD": TradingConstantDefinition(
        name="PRICE_DECIMALS_GOLD",
        value=2,
        unit="Decimal Digits",
        category=ConstantCategory.BROKER_PROTOCOL,
        min_value=2,
        max_value=2,
        symbol_scope="XAUUSD",
        provenance_source="cTrader Symbol Directory: XAUUSD Digits=2",
        rationale="Gold pricing is quoted in 2 decimal places ($0.01 precision)."
    ),
    "MIN_SL_SPREAD_MULTIPLIER": TradingConstantDefinition(
        name="MIN_SL_SPREAD_MULTIPLIER",
        value=4.0,
        unit="Multiplier (x Spread)",
        category=ConstantCategory.BROKER_PROTOCOL,
        min_value=2.0,
        max_value=10.0,
        symbol_scope="GLOBAL",
        provenance_source="Broker Stop-Level Constraints & Dynamic Slippage Defense",
        rationale="cTrader brokers reject or instantly trigger stop orders placed inside the current spread buffer."
    ),

    # --- CATEGORY B: SAFETY POLICY ---
    "MAX_ACCOUNT_RISK_PERCENT": TradingConstantDefinition(
        name="MAX_ACCOUNT_RISK_PERCENT",
        value=1.0,
        unit="Percent of Equity",
        category=ConstantCategory.SAFETY_POLICY,
        min_value=0.25,
        max_value=2.0,
        symbol_scope="GLOBAL",
        provenance_source="Institutional Risk Standard (Basel III / Quantitative Prop Trading Standard)",
        rationale="Limits maximum monetary risk on any single position to <= 1.0% of total account equity."
    ),
    "DAILY_LOSS_LIMIT_DOLLARS": TradingConstantDefinition(
        name="DAILY_LOSS_LIMIT_DOLLARS",
        value=5.00,
        unit="USD",
        category=ConstantCategory.SAFETY_POLICY,
        min_value=1.00,
        max_value=50.00,
        symbol_scope="GLOBAL",
        provenance_source="Micro-Account Circuit Breaker Policy ($1,000 baseline / Demo Tier)",
        rationale="Hard daily drawdown halt. If realized losses exceed $5.00 in a 24h rolling window, trading locks out for the day."
    ),
    "MAX_CONSECUTIVE_LOSSES": TradingConstantDefinition(
        name="MAX_CONSECUTIVE_LOSSES",
        value=3,
        unit="Count",
        category=ConstantCategory.SAFETY_POLICY,
        min_value=2,
        max_value=5,
        symbol_scope="GLOBAL",
        provenance_source="Anti-Tilt & Regime Invalidation Risk Policy",
        rationale="Three consecutive stop-outs indicate market regime transition; triggers mandatory 60m cooldown."
    ),
    "MAX_CONCURRENT_POSITIONS": TradingConstantDefinition(
        name="MAX_CONCURRENT_POSITIONS",
        value=1,
        unit="Count",
        category=ConstantCategory.SAFETY_POLICY,
        min_value=1,
        max_value=3,
        symbol_scope="GLOBAL",
        provenance_source="Single-Position Sniper Capital Allocation Mandate",
        rationale="Prevents correlated margin over-allocation by allowing exactly 1 active trade at a time."
    ),
    "MAX_AUTONOMOUS_LOT_SIZE": TradingConstantDefinition(
        name="MAX_AUTONOMOUS_LOT_SIZE",
        value=0.05,
        unit="Lots",
        category=ConstantCategory.SAFETY_POLICY,
        min_value=0.01,
        max_value=1.0,
        symbol_scope="GLOBAL",
        provenance_source="Autonomous Trading Safety Policy Limits",
        rationale="Caps maximum autonomous order size per dispatch to 0.05 lots."
    ),

    "MIN_SL_BUFFER_GOLD": TradingConstantDefinition(
        name="MIN_SL_BUFFER_GOLD",
        value=2.50,
        unit="USD ($)",
        category=ConstantCategory.SAFETY_POLICY,
        min_value=1.50,
        max_value=10.00,
        symbol_scope="XAUUSD",
        provenance_source="Gold Noise Floor Regression Analysis (September 2026 Audit)",
        rationale="Guarantees minimum $2.50 (25 pips) breathing room on Gold to prevent spread-spike premature stopouts."
    ),
    "MIN_RR_RATIO": TradingConstantDefinition(
        name="MIN_RR_RATIO",
        value=2.0,
        unit="Ratio (1:X)",
        category=ConstantCategory.SAFETY_POLICY,
        min_value=1.5,
        max_value=5.0,
        symbol_scope="GLOBAL",
        provenance_source="Mathematical Positive Expectancy Mandate",
        rationale="Ensures positive mathematical expectancy. At 40% win rate, 1:2.0 R:R yields net positive expectancy."
    ),
    "PRE_NEWS_BLACKOUT_MINUTES": TradingConstantDefinition(
        name="PRE_NEWS_BLACKOUT_MINUTES",
        value=30,
        unit="Minutes",
        category=ConstantCategory.SAFETY_POLICY,
        min_value=15,
        max_value=60,
        symbol_scope="GLOBAL",
        provenance_source="Rule 6 Defense-in-Depth News Protection Architecture",
        rationale="Halts new orders 30 minutes before high-impact CPI/NFP/FOMC events to avoid slippage."
    ),
    "POST_NEWS_COOLDOWN_MINUTES": TradingConstantDefinition(
        name="POST_NEWS_COOLDOWN_MINUTES",
        value=15,
        unit="Minutes",
        category=ConstantCategory.SAFETY_POLICY,
        min_value=5,
        max_value=30,
        symbol_scope="GLOBAL",
        provenance_source="Rule 7 Post-News Volatility Normalization Architecture",
        rationale="Allows broker spread and order book depth to normalize for 15 minutes post-event."
    ),
    "ANTI_FLIP_COOLDOWN_SECONDS": TradingConstantDefinition(
        name="ANTI_FLIP_COOLDOWN_SECONDS",
        value=60,
        unit="Seconds",
        category=ConstantCategory.SAFETY_POLICY,
        min_value=30,
        max_value=300,
        symbol_scope="GLOBAL",
        provenance_source="Position Manager V3 Anti-Whiplash Safeguard",
        rationale="Blocks opposite direction entries for 60s after closing a position to eliminate spread churn."
    ),

    # --- CATEGORY C: STRATEGY CONFIGURATION ---
    "MIN_CONSENSUS_AGENTS": TradingConstantDefinition(
        name="MIN_CONSENSUS_AGENTS",
        value=4,
        unit="Count (out of 7)",
        category=ConstantCategory.STRATEGY_CONFIG,
        min_value=4,
        max_value=7,
        symbol_scope="GLOBAL",
        provenance_source="Multi-Agent Consensus Architecture Specification",
        rationale="Requires supermajority agreement (at least 4 out of 7 agents) before trade dispatch."
    ),
    "MIN_AGENT_CONFIDENCE_THRESHOLD": TradingConstantDefinition(
        name="MIN_AGENT_CONFIDENCE_THRESHOLD",
        value=65.0,
        unit="Score (0-100)",
        category=ConstantCategory.STRATEGY_CONFIG,
        min_value=50.0,
        max_value=90.0,
        symbol_scope="GLOBAL",
        provenance_source="TradeTalk Strategy Configuration & User Settings",
        rationale="Individual agent conviction threshold to count as an agreeing vote."
    ),
    "BREAK_EVEN_TRIGGER_R": TradingConstantDefinition(
        name="BREAK_EVEN_TRIGGER_R",
        value=1.0,
        unit="R-Multiple (1R = Initial SL Distance)",
        category=ConstantCategory.STRATEGY_CONFIG,
        min_value=0.8,
        max_value=2.0,
        symbol_scope="GLOBAL",
        provenance_source="Position Manager V3 Canonical 1R Architecture",
        rationale="Locks SL to Break-Even (Entry + 1 pip buffer) once market moves >= +1.0R into profit."
    ),
    "REGIME_ADX_MINIMUM": TradingConstantDefinition(
        name="REGIME_ADX_MINIMUM",
        value=20.0,
        unit="ADX (15m)",
        category=ConstantCategory.STRATEGY_CONFIG,
        min_value=10.0,
        max_value=40.0,
        symbol_scope="XAUUSD",
        provenance_source="Phase 5 Controlled Optimization — Minimum Viable Improvement",
        rationale="Prospective Phase 6 candidate gate: block entries when 15m ADX is below 20.0."
    ),
    "DISALLOW_CONSOLIDATION_ENTRIES": TradingConstantDefinition(
        name="DISALLOW_CONSOLIDATION_ENTRIES",
        value=True,
        unit="Boolean",
        category=ConstantCategory.STRATEGY_CONFIG,
        symbol_scope="XAUUSD",
        provenance_source="Phase 5 Controlled Optimization — Minimum Viable Improvement",
        rationale="Prospective Phase 6 candidate gate: explicitly veto entries while market structure is classified as consolidation/range."
    ),

    "TRAILING_START_R": TradingConstantDefinition(
        name="TRAILING_START_R",
        value=1.5,
        unit="R-Multiple",
        category=ConstantCategory.STRATEGY_CONFIG,
        min_value=1.2,
        max_value=3.0,
        symbol_scope="GLOBAL",
        provenance_source="Position Manager V3 Canonical 1R Architecture",
        rationale="Activates dynamic structural trailing stop once market moves >= +1.5R into profit."
    ),

    # --- CATEGORY D: MARKET-DERIVED ADAPTIVE PARAMETERS ---
    "MAX_ALLOWED_SPREAD_XAUUSD": TradingConstantDefinition(
        name="MAX_ALLOWED_SPREAD_XAUUSD",
        value=0.55,
        unit="USD ($)",
        category=ConstantCategory.MARKET_DERIVED,
        min_value=0.20,
        max_value=1.50,
        symbol_scope="XAUUSD",
        provenance_source="cTrader Live Liquidity Percentile & Volatility Engine",
        rationale="Maximum permissible spread for Gold execution. Can adapt up to $1.20 in FOMC Cautious Mode.",
        is_adaptive=True
    ),
    "DYNAMIC_SL_ATR_MULTIPLIER": TradingConstantDefinition(
        name="DYNAMIC_SL_ATR_MULTIPLIER",
        value=1.5,
        unit="Multiplier (x 15M ATR)",
        category=ConstantCategory.MARKET_DERIVED,
        min_value=1.0,
        max_value=3.0,
        symbol_scope="GLOBAL",
        provenance_source="Volatility Engine Dynamic ATR Adapter",
        rationale="Adapts SL breathing room to market volatility regime (Low, Normal, High, Extreme).",
        is_adaptive=True
    ),

    # --- CATEGORY E: IMPLEMENTATION CONSTANTS ---
    "MAX_DATA_AGE_SECONDS": TradingConstantDefinition(
        name="MAX_DATA_AGE_SECONDS",
        value=5.0,
        unit="Seconds",
        category=ConstantCategory.IMPLEMENTATION,
        min_value=1.0,
        max_value=15.0,
        symbol_scope="GLOBAL",
        provenance_source="Market Data Integrity Monitor Freshness Spec",
        rationale="Market tick quotes older than 5.0 seconds are classified as STALE and fail closed."
    ),
    "IDEMPOTENCY_LOCK_TTL_SECONDS": TradingConstantDefinition(
        name="IDEMPOTENCY_LOCK_TTL_SECONDS",
        value=30.0,
        unit="Seconds",
        category=ConstantCategory.IMPLEMENTATION,
        min_value=10.0,
        max_value=120.0,
        symbol_scope="GLOBAL",
        provenance_source="Execution Engine Idempotency Architecture",
        rationale="Prevents duplicate HTTP / double-click execution requests by locking intent ID for 30s."
    )
}

class TradingConfigManager:
    """Centralized accessor and validator for all registered trading constants."""
    version: str = "2.1.0-DEMO-CANDIDATE"
    
    @staticmethod
    def get(name: str) -> Any:
        if name in TRADING_CONSTANTS_REGISTRY:
            return TRADING_CONSTANTS_REGISTRY[name].value
        raise KeyError(f"CRITICAL: Unregistered trading constant requested: '{name}'. Magic numbers prohibited.")

    @staticmethod
    def get_definition(name: str) -> TradingConstantDefinition:
        if name in TRADING_CONSTANTS_REGISTRY:
            return TRADING_CONSTANTS_REGISTRY[name]
        raise KeyError(f"CRITICAL: Unregistered trading constant: '{name}'")

    @staticmethod
    def list_all() -> Dict[str, Dict[str, Any]]:
        res = {}
        for k, v in TRADING_CONSTANTS_REGISTRY.items():
            if hasattr(v, "model_dump"):
                res[k] = v.model_dump()
            else:
                res[k] = v.dict()
        return res

trading_config = TradingConfigManager()



