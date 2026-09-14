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

    def test_consensus_registry_is_four_of_six(self):
        from app.config import trading_config
        definition = trading_config.get_definition("MIN_CONSENSUS_AGENTS")
        self.assertEqual(definition.value, 4)
        self.assertEqual(definition.max_value, 6)


if __name__ == "__main__":
    unittest.main()
