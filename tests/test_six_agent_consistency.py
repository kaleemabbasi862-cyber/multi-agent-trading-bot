import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class TestSixAgentConsistency(unittest.TestCase):
    def test_production_sources_have_no_stale_seven_agent_labels(self):
        files = [
            ROOT / "main_native.py",
            ROOT / "copilot_agent.py",
            ROOT / "app" / "config.py",
            ROOT / "app" / "services" / "autonomous_trader.py",
            ROOT / "app" / "routers" / "signals.py",
        ]
        stale = ("7-agent", "7-Agent", "7-AGENT", "7 agents", "out of 7")
        for path in files:
            text = path.read_text(encoding="utf-8")
            for token in stale:
                self.assertNotIn(token, text, f"{path.name} still contains {token!r}")

    def test_canonical_specialist_weights_sum_to_one(self):
        from app.agents.head_desk_agent import HeadDeskManagerAgent
        self.assertEqual(len(HeadDeskManagerAgent.WEIGHTS), 5)
        self.assertAlmostEqual(sum(HeadDeskManagerAgent.WEIGHTS.values()), 1.0, places=12)

    def test_specialist_metadata_matches_head_desk_weights(self):
        from app.agents.head_desk_agent import HeadDeskManagerAgent
        from app.agents.technical_agent import technical_agent
        from app.agents.fundamental_agent import fundamental_agent
        from app.agents.liquidity_agent import liquidity_agent
        from app.agents.quality_agent import quality_agent
        from app.agents.risk_agent import risk_agent
        agents = [technical_agent, fundamental_agent, liquidity_agent, quality_agent, risk_agent]
        for agent in agents:
            self.assertAlmostEqual(agent.weight, HeadDeskManagerAgent.WEIGHTS[agent.name], places=12)

    def test_consensus_engine_does_not_import_legacy_regime_agent(self):
        text = (ROOT / "app" / "engine" / "consensus_engine.py").read_text(encoding="utf-8")
        self.assertNotIn("regime_agent", text)
        self.assertIn("all_agent_decisions = [", text)

    def test_consensus_registry_is_four_of_six(self):
        from app.config import trading_config
        definition = trading_config.get_definition("MIN_CONSENSUS_AGENTS")
        self.assertEqual(definition.value, 4)
        self.assertEqual(definition.max_value, 6)


if __name__ == "__main__":
    unittest.main()
