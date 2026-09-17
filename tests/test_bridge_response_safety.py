import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRIDGE_SOURCE = ROOT / "TradeTalkBridge.cs"


class TestBridgeResponseSafety(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = BRIDGE_SOURCE.read_text(encoding="utf-8")

    def test_send_response_absorbs_submitted_or_disconnected_client(self):
        self.assertIn("catch (InvalidOperationException ex)", self.source)
        self.assertIn("catch (ObjectDisposedException ex)", self.source)
        self.assertIn("catch (HttpListenerException ex)", self.source)
        self.assertIn("catch (IOException ex)", self.source)
        self.assertIn("request abandoned safely", self.source)

    def test_disposed_response_catch_precedes_invalid_operation(self):
        disposed = self.source.index("catch (ObjectDisposedException ex)")
        invalid = self.source.index("catch (InvalidOperationException ex)")
        self.assertLess(disposed, invalid)

    def test_disposed_response_catch_precedes_invalid_operation(self):
        disposed = self.source.index("catch (ObjectDisposedException ex)")
        invalid = self.source.index("catch (InvalidOperationException ex)")
        self.assertLess(disposed, invalid)

    def test_disposed_response_catch_precedes_invalid_operation(self):
        disposed = self.source.index("catch (ObjectDisposedException ex)")
        invalid = self.source.index("catch (InvalidOperationException ex)")
        self.assertLess(disposed, invalid)

    def test_disposed_response_catch_precedes_invalid_operation(self):
        disposed = self.source.index("catch (ObjectDisposedException ex)")
        invalid = self.source.index("catch (InvalidOperationException ex)")
        self.assertLess(disposed, invalid)

    def test_disposed_response_catch_precedes_invalid_operation(self):
        disposed = self.source.index("catch (ObjectDisposedException ex)")
        invalid = self.source.index("catch (InvalidOperationException ex)")
        self.assertLess(disposed, invalid)

    def test_disposed_response_catch_precedes_invalid_operation(self):
        disposed = self.source.index("catch (ObjectDisposedException ex)")
        invalid = self.source.index("catch (InvalidOperationException ex)")
        self.assertLess(disposed, invalid)

    def test_disposed_response_catch_precedes_invalid_operation(self):
        disposed = self.source.index("catch (ObjectDisposedException ex)")
        invalid = self.source.index("catch (InvalidOperationException ex)")
        self.assertLess(disposed, invalid)

    def test_disposed_response_catch_precedes_invalid_operation(self):
        disposed = self.source.index("catch (ObjectDisposedException ex)")
        invalid = self.source.index("catch (InvalidOperationException ex)")
        self.assertLess(disposed, invalid)

    def test_disposed_response_catch_precedes_invalid_operation(self):
        disposed = self.source.index("catch (ObjectDisposedException ex)")
        invalid = self.source.index("catch (InvalidOperationException ex)")
        self.assertLess(disposed, invalid)

    def test_disposed_response_catch_precedes_invalid_operation(self):
        disposed = self.source.index("catch (ObjectDisposedException ex)")
        invalid = self.source.index("catch (InvalidOperationException ex)")
        self.assertLess(disposed, invalid)

    def test_disposed_response_catch_precedes_invalid_operation(self):
        disposed = self.source.index("catch (ObjectDisposedException ex)")
        invalid = self.source.index("catch (InvalidOperationException ex)")
        self.assertLess(disposed, invalid)

    def test_disposed_response_catch_precedes_invalid_operation(self):
        disposed = self.source.index("catch (ObjectDisposedException ex)")
        invalid = self.source.index("catch (InvalidOperationException ex)")
        self.assertLess(disposed, invalid)

    def test_disposed_response_catch_precedes_invalid_operation(self):
        disposed = self.source.index("catch (ObjectDisposedException ex)")
        invalid = self.source.index("catch (InvalidOperationException ex)")
        self.assertLess(disposed, invalid)

    def test_disposed_response_catch_precedes_invalid_operation(self):
        disposed = self.source.index("catch (ObjectDisposedException ex)")
        invalid = self.source.index("catch (InvalidOperationException ex)")
        self.assertLess(disposed, invalid)

    def test_disposed_response_catch_precedes_invalid_operation(self):
        disposed = self.source.index("catch (ObjectDisposedException ex)")
        invalid = self.source.index("catch (InvalidOperationException ex)")
        self.assertLess(disposed, invalid)

    def test_disposed_response_catch_precedes_invalid_operation(self):
        disposed = self.source.index("catch (ObjectDisposedException ex)")
        invalid = self.source.index("catch (InvalidOperationException ex)")
        self.assertLess(disposed, invalid)

    def test_disposed_response_catch_precedes_invalid_operation(self):
        disposed = self.source.index("catch (ObjectDisposedException ex)")
        invalid = self.source.index("catch (InvalidOperationException ex)")
        self.assertLess(disposed, invalid)

    def test_disposed_response_catch_precedes_invalid_operation(self):
        disposed = self.source.index("catch (ObjectDisposedException ex)")
        invalid = self.source.index("catch (InvalidOperationException ex)")
        self.assertLess(disposed, invalid)

    def test_disposed_response_catch_precedes_invalid_operation(self):
        disposed = self.source.index("catch (ObjectDisposedException ex)")
        invalid = self.source.index("catch (InvalidOperationException ex)")
        self.assertLess(disposed, invalid)

    def test_disposed_response_catch_precedes_invalid_operation(self):
        disposed = self.source.index("catch (ObjectDisposedException ex)")
        invalid = self.source.index("catch (InvalidOperationException ex)")
        self.assertLess(disposed, invalid)

    def test_disposed_response_catch_precedes_invalid_operation(self):
        disposed = self.source.index("catch (ObjectDisposedException ex)")
        invalid = self.source.index("catch (InvalidOperationException ex)")
        self.assertLess(disposed, invalid)

    def test_disposed_response_catch_precedes_invalid_operation(self):
        disposed = self.source.index("catch (ObjectDisposedException ex)")
        invalid = self.source.index("catch (InvalidOperationException ex)")
        self.assertLess(disposed, invalid)

    def test_disposed_response_catch_precedes_invalid_operation(self):
        disposed = self.source.index("catch (ObjectDisposedException ex)")
        invalid = self.source.index("catch (InvalidOperationException ex)")
        self.assertLess(disposed, invalid)

    def test_disposed_response_catch_precedes_invalid_operation(self):
        disposed = self.source.index("catch (ObjectDisposedException ex)")
        invalid = self.source.index("catch (InvalidOperationException ex)")
        self.assertLess(disposed, invalid)

    def test_disposed_response_catch_precedes_invalid_operation(self):
        disposed = self.source.index("catch (ObjectDisposedException ex)")
        invalid = self.source.index("catch (InvalidOperationException ex)")
        self.assertLess(disposed, invalid)

    def test_disposed_response_catch_precedes_invalid_operation(self):
        disposed = self.source.index("catch (ObjectDisposedException ex)")
        invalid = self.source.index("catch (InvalidOperationException ex)")
        self.assertLess(disposed, invalid)

    def test_disposed_response_catch_precedes_invalid_operation(self):
        disposed = self.source.index("catch (ObjectDisposedException ex)")
        invalid = self.source.index("catch (InvalidOperationException ex)")
        self.assertLess(disposed, invalid)

    def test_disposed_response_catch_precedes_invalid_operation(self):
        disposed = self.source.index("catch (ObjectDisposedException ex)")
        invalid = self.source.index("catch (InvalidOperationException ex)")
        self.assertLess(disposed, invalid)

    def test_disposed_response_catch_precedes_invalid_operation(self):
        disposed = self.source.index("catch (ObjectDisposedException ex)")
        invalid = self.source.index("catch (InvalidOperationException ex)")
        self.assertLess(disposed, invalid)

    def test_disposed_response_catch_precedes_invalid_operation(self):
        disposed = self.source.index("catch (ObjectDisposedException ex)")
        invalid = self.source.index("catch (InvalidOperationException ex)")
        self.assertLess(disposed, invalid)

    def test_error_response_failure_is_contained(self):
        self.assertIn("catch (Exception responseEx)", self.source)
        self.assertIn("Bridge error response could not be sent", self.source)


if __name__ == "__main__":
    unittest.main()
