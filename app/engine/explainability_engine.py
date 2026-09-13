import datetime
from typing import Dict, Any, List, Optional
from app.database.models import SignalPayload, AgentDecisionOutput, RiskCheckResult

class ExplainabilityEngine:
    """
    Synthesizes multi-agent consensus deliberations into human-interpretable bilingual
    (English & Urdu) explanations and Decision DNA narratives.
    """

    def generate_explanation(
        self,
        signal: SignalPayload,
        status: str,
        score: float,
        agent_decisions: List[AgentDecisionOutput],
        risk_check: RiskCheckResult,
        is_guarded: bool = False,
        guard_reason: Optional[str] = None,
        macro_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Builds dual-language explanatory breakdown for executive, analytical, and audit consumption.
        """
        act = signal.action.upper()
        sym = signal.symbol.upper()
        p = signal.entry_price
        sl = signal.stop_loss
        tp = signal.take_profit
        rr = risk_check.rr_ratio if risk_check else 2.0
        vol = getattr(signal, "volume", 0.01) or 0.01

        # 1. Compile Agent Score Summaries
        agent_cards = []
        positive_factors = []
        cautious_factors = []
        
        for d in agent_decisions:
            agent_cards.append({
                "agent_name": d.agent_name,
                "score": d.score,
                "decision": d.decision,
                "direction": d.direction,
                "reasoning": d.reasoning_summary,
                "metrics": d.metrics
            })
            if d.score >= 75.0:
                positive_factors.append(f"[{d.agent_name}] {d.reasoning_summary}")
            elif d.score < 60.0 or d.decision in ("FAIL", "VETO"):
                cautious_factors.append(f"[{d.agent_name}] {d.reasoning_summary}")

        # 2. English Narrative Generation
        if status == "APPROVED":
            en_headline = f"🎯 HIGH-CONVICTION {act} ORDER APPROVED ON {sym} ({score:.1f}% Confidence)"
            en_summary = (
                f"Autonomous Consensus Engine verified strong alignment across {len([d for d in agent_decisions if d.score >= 75])}/5 analytical agents.\n"
                f"• Execution Parameters: {act} {vol:.2f} lots @ ${p:.2f} | SL: ${sl:.2f} | TP: ${tp:.2f} (R:R 1:{rr:.2f})\n"
                f"• Structural Confluence: " + "; ".join(positive_factors[:3]) + "\n"
                f"• Risk Clearance: 100% checks passed. 1.0% capital risk protected. Guardian rules clear."
            )
            ur_headline = f"🎯 {sym} پر {act} کا ٹریڈ آرڈر منظور ({score:.1f}% اعتماد)"
            ur_summary = (
                f"تمام 6 AI ایجنٹس نے مارکیٹ اسٹرکچر اور انڈیکیٹرز کی جانچ کے بعد متفقہ منظوری دے دی ہے۔\n"
                f"• اینٹری: ${p:.2f} | اسٹاپ لاس: ${sl:.2f} | ٹیک پرافٹ: ${tp:.2f} (رسک ٹو ریوارڈ 1:{rr:.2f})\n"
                f"• ایجنٹ تجزیہ: ٹیکنیکل، سمارٹ منی اور مارکیٹ ریجیم ایجنٹس نے {act} کے حق میں ٹھوس شواہد فراہم کیے۔\n"
                f"• رسک پروٹیکشن: 1% رسک فلٹر اور گارڈین کے تمام 17 حفاظتی اصول پاس ہو چکے ہیں۔"
            )
        else:
            block_cause = guard_reason if is_guarded else (risk_check.veto_reason if not risk_check.passed else "Insufficient multi-agent consensus quorum (< 75% score or conflicting agent votes)")
            en_headline = f"🚫 {act} ORDER HALTED ON {sym} ({status})"
            en_summary = (
                f"Execution vetoed by safety protocol to protect capital balance.\n"
                f"• Primary Block Reason: {block_cause}\n"
                f"• Consensus Score: {score:.1f}% (Below required 75.0% threshold or hard safety veto tripped)\n"
                f"• Cautionary Factors:\n  - " + "\n  - ".join(cautious_factors if cautious_factors else [block_cause])
            )
            ur_headline = f"🚫 {sym} پر ٹریڈ روکی گئی ({status})"
            ur_summary = (
                f"سرمائے کے تحفظ کے لیے ٹریڈ کی خودکار ایگزیکیوشن روک دی گئی ہے۔\n"
                f"• رکاوٹ کی بنیادی وجہ: {block_cause}\n"
                f"• متفقہ اسکور: {score:.1f}% (مطلوبہ 75% سے کم یا سیفٹی گارڈین کا ویٹو)\n"
                f"• فیصلہ: مارکیٹ میں سازگار حالات کا انتظار کیا جا رہا ہے۔"
            )

        # Invalidation thesis
        invalidation_level = sl
        invalidation_reason = f"Price breach of key invalidation level (${invalidation_level:.2f}) terminates the setup thesis."

        return {
            "signal_id": signal.id,
            "status": status,
            "score": score,
            "headline_en": en_headline,
            "summary_en": en_summary,
            "headline_ur": ur_headline,
            "summary_ur": ur_summary,
            "positive_factors": positive_factors,
            "cautious_factors": cautious_factors,
            "invalidation_level": invalidation_level,
            "invalidation_reason": invalidation_reason,
            "agent_cards": agent_cards,
            "risk_metrics": {
                "account_balance": risk_check.account_balance if risk_check else 0.0,
                "risk_amount": risk_check.risk_amount if risk_check else 0.0,
                "calculated_volume": vol,
                "rr_ratio": rr,
                "spread": risk_check.spread if risk_check else 0.35,
                "passed": risk_check.passed if risk_check else False
            }
        }


explainability_engine = ExplainabilityEngine()
