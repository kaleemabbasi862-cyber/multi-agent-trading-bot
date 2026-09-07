from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

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

class AgentDecisionOutput(BaseModel):
    agent_name: str
    direction: str  # BUY, SELL, NEUTRAL
    score: float  # 0.0 - 100.0
    decision: str  # PASS, FAIL, VETO, NEUTRAL
    reasoning_summary: str
    metrics: Dict[str, Any] = Field(default_factory=dict)

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

class ConsensusResult(BaseModel):
    signal_id: str
    symbol: str
    direction: str
    decision_status: str  # APPROVED, CONDITIONAL, WATCHLIST, REJECTED, BLOCKED
    decision_score: float
    agent_decisions: List[AgentDecisionOutput]
    risk_check: RiskCheckResult
    full_analysis: str
    execution_result: Optional[Dict[str, Any]] = None
    decision_dna_id: Optional[str] = None

class BacktestRequest(BaseModel):
    strategy_name: str = "Gold_Sniper_SMC_v2"
    symbol: str = "XAUUSD"
    timeframe: str = "15m"
    days_back: int = 30
    initial_balance: float = 1000.0
    spread_pips: float = 3.5
    slippage_pips: float = 1.0
    commission_per_lot: float = 6.0
