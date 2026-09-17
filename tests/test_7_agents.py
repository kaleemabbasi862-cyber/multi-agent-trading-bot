from app.database.models import SignalPayload
from app.agents.technical_agent import technical_agent
from app.agents.fundamental_agent import fundamental_agent
from app.agents.liquidity_agent import liquidity_agent
from app.agents.quality_agent import quality_agent
from app.agents.head_desk_agent import head_desk_agent
from app.agents.risk_agent import risk_agent

def test_all_6_agents_evaluate_valid_setup():
    sig = SignalPayload(
        symbol="XAUUSD",
        action="BUY",
        entry_price=2750.0,
        stop_loss=2744.0,
        take_profit=2762.0,
        timeframe="15m"
    )
    market_data = {
        "source": "CTRADER_CBOT",
        "candle_source": "CTRADER_CBOT",
        "updated_at": __import__("time").time(),
        "price": 2750.0,
        "spread": 0.35,
        "high_24h": 2765.0,
        "low_24h": 2735.0,
        "indicators": {
            "rsi": 54.0,
            "ema_20": 2748.0,
            "ema_50": 2745.0,
            "ema_200": 2738.0,
            "ema_20_1h": 2747.0,
            "ema_50_1h": 2742.0,
            "trend_1h": "BULLISH",
            "support": 2740.0,
            "resistance": 2760.0
        }
    }
    macro_data = {
        "minutes_to_next_high_impact_news": 180,
        "minutes_since_last_event": 120,
        "usd_sentiment": "NEUTRAL"
    }
    account_status = {
        "balance": 1000.0,
        "equity": 1000.0,
        "free_margin": 1000.0,
        "open_positions": [],
        "daily_loss": 0.0
    }
    hist_stats = {"closed_trades": 30, "win_rate": 65.0, "profit_factor": 1.7}

    t_dec = technical_agent.evaluate(sig, market_data)
    f_dec = fundamental_agent.evaluate(sig, macro_data)
    r_dec, risk_check = risk_agent.evaluate(sig, account_status, market_data)
    l_dec = liquidity_agent.evaluate(sig, market_data)
    q_dec = quality_agent.evaluate(sig, hist_stats, market_data)

    all_decs = [t_dec, f_dec, l_dec, q_dec, r_dec]
    assert len(all_decs) == 5

    status, score, explanation = head_desk_agent.arbitrate(
        signal=sig,
        agent_decisions=all_decs,
        risk_check=risk_check
    )

    assert status == "APPROVED"
    assert score >= 75.0
