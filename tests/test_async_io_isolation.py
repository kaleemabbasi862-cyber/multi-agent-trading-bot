import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
MAIN = ROOT / "main_native.py"


class TestAsyncIoIsolation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = MAIN.read_text(encoding="utf-8")

    def test_status_endpoint_offloads_gateway_sync(self):
        self.assertIn(
            "return await asyncio.to_thread(ctrader_cloud_gateway.get_gateway_status)",
            self.source,
        )

    def test_local_bridge_poll_is_offloaded(self):
        self.assertIn(
            "await asyncio.to_thread(ctrader_cloud_gateway.sync_local_cbot_telemetry, 2.5)",
            self.source,
        )

    def test_cloud_sync_is_offloaded(self):
        self.assertIn(
            "await asyncio.to_thread(ctrader_cloud_gateway.sync_with_spotware_cloud)",
            self.source,
        )

    def test_cloud_heartbeat_post_is_offloaded(self):
        self.assertIn(
            "await asyncio.to_thread(requests.post, f\"{cloud_url}/api/cbot/heartbeat\"",
            self.source,
        )


if __name__ == "__main__":
    unittest.main()
