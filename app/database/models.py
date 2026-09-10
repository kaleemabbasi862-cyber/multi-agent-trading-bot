from typing import Optional, List, Dict, Any
from enum import Enum
from pydantic import BaseModel, Field

class AgentOperationalCriticality(str, Enum):
    SAFETY_CRITICAL = "SAFETY-CRITICAL"
    DECISION_CRITICAL = "DECISION-CRITICAL"
    OPTIONAL = "OPTIONAL"

class AgentHealthStatus(str, Enum):
    HEALTHY = "HEALTHY"
    STALE = "STALE"
    STALE_DATA = "STALE_DATA"
    UNAVAILABLE = "UNAVAILABLE"
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"
    DEGRADED = "DEGRADED"
    INVALID_INPUT = "INVALID_INPUT"


class SystemDecisionState(str, Enum):
    APPROVED = "APPROVED"
    NO_TRADE = "NO_TRADE"
    BLOCKED = "BLOCKED"
    DEGRADED_NO_TRADE = "DEGRADED_NO_TRADE"
    DATA_UNAVAILABLE = "DATA_UNAVAILABLE"
    BROKER_STATE_UNCERTAIN = "BROKER_STATE_UNCERTAIN"

class DataProvenance(str, Enum):
    BROKER_DEMO_VERIFIED = "BROKER_DEMO_VERIFIED"
    BROKER_LIVE_VERIFIED = "BROKER_LIVE_VERIFIED"
    BROKER_DEMO = "BROKER_DEMO"
    BROKER_LIVE = "BROKER_LIVE"
    SIMULATED = "SIMULATED"
    PAPER = "PAPER"
    BACKTEST = "BACKTEST"
    TEST = "TEST"
    LEGACY = "LEGACY"
    SEEDED = "SEEDED"
    UNKNOWN = "UNKNOWN"

class SignalPayload(BaseModel):
    id: Optional[str] = None
    symbol: str = "XAUUSD"
    action: str  # BUY or SELL
    entry_price: float
    stop_loss: float
    take_profit: float
    timeframe: str = "15m"
    strategy_name: str = "GoldSniper_MTF_1H"
    source: str = "MANUAL_OR_SCANNER"
    volume: Optional[float] = 0.01
    timestamp: Optional[str] = None
    account_id: Optional[str] = "5908018"
    execution_intent_id: Optional[str] = None
    data_provenance: str = DataProvenance.BROKER_DEMO

class AgentDecisionOutput(BaseModel):
    agent_name: str
    direction: str = "NEUTRAL"  # BUY, SELL, NEUTRAL
    score: float = 0.0  # 0.0 - 100.0
    decision: str = "NEUTRAL"  # PASS, FAIL, VETO, NEUTRAL, CONDITIONAL_PASS
    reasoning_summary: str = ""
    metrics: Dict[str, Any] = Field(default_factory=dict)
    
    # Phase 2 Health Contract
    operational_criticality: str = AgentOperationalCriticality.DECISION_CRITICAL
    health_status: str = AgentHealthStatus.HEALTHY
    execution_started_at: Optional[str] = None
    execution_completed_at: Optional[str] = None
    execution_latency_ms: float = 0.0
    input_timestamp: Optional[str] = None
    data_age_seconds: Optional[float] = None
    data_source: str = "cTrader Open API / Real-Time Feed"
    confidence: float = 0.0
    error: Optional[str] = None
    stale: bool = False
    fallback_used: bool = False
    decision_id: Optional[str] = None

class RiskCheckResult(BaseModel):
    passed: bool
    account_balance: float
    account_equity: float
    risk_amount: float
    calculated_volume: float
    sl_distance: float
    tp_distance: float
    rr_ratio: float
    spread: float
    veto_reason: Optional[str] = None
    initial_r: Optional[float] = None
    data_provenance: str = DataProvenance.BROKER_DEMO

class ConsensusResult(BaseModel):
    signal_id: str
    symbol: str
    direction: str
    decision_status: str  # APPROVED, NO_TRADE, BLOCKED, DEGRADED_NO_TRADE, DATA_UNAVAILABLE, BROKER_STATE_UNCERTAIN
    decision_score: float
    agent_decisions: List[AgentDecisionOutput]
    risk_check: RiskCheckResult
    full_analysis: str
    execution_result: Optional[Dict[str, Any]] = None
    decision_dna_id: Optional[str] = None
    execution_intent_id: Optional[str] = None
    system_state: str = SystemDecisionState.NO_TRADE
    critical_agent_failures: List[str] = Field(default_factory=list)

class BacktestRequest(BaseModel):
    strategy_name: str = "Gold_Sniper_SMC_v2"
    symbol: str = "XAUUSD"
    timeframe: str = "15m"
    days_back: int = 30
    initial_balance: float = 1000.0
    spread_pips: float = 3.5
    slippage_pips: float = 1.0
    commission_per_lot: float = 6.0
