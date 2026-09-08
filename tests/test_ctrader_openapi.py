import unittest
import struct
import ctrader_openapi

class TestCTraderOpenAPI(unittest.TestCase):
    def test_varint_encoding_decoding(self):
        test_values = [0, 1, 127, 128, 300, 2100, 2106, 5908018, 100000000]
        for val in test_values:
            encoded = ctrader_openapi.encode_varint(val)
            decoded, offset = ctrader_openapi.decode_varint(encoded, 0)
            self.assertEqual(val, decoded)
            self.assertEqual(len(encoded), offset)

    def test_proto_message_framing(self):
        # Create a payload for ProtoOAApplicationAuthReq
        payload = (
            ctrader_openapi.enc_field_str(1, "test_client_id") +
            ctrader_openapi.enc_field_str(2, "test_client_secret")
        )
        msg_bytes = ctrader_openapi.enc_proto_message(
            payload_type=2100,
            payload_bytes=payload,
            client_msg_id="TEST_FRAME"
        )
        # Check 4-byte length prefix
        self.assertGreaterEqual(len(msg_bytes), 4)
        length_prefix = struct.unpack(">I", msg_bytes[:4])[0]
        body = msg_bytes[4:]
        self.assertEqual(length_prefix, len(body))

        # Decode body
        parsed = ctrader_openapi.decode_proto_message(body)
        self.assertEqual(parsed["payload_type"], 2100)
        self.assertEqual(parsed["client_msg_id"], "TEST_FRAME")

        # Decode inner payload fields
        inner_fields = ctrader_openapi.decode_proto_fields(parsed["payload"])
        self.assertEqual(inner_fields[1][0].decode("utf-8"), "test_client_id")
        self.assertEqual(inner_fields[2][0].decode("utf-8"), "test_client_secret")

    def test_order_req_encoding(self):
        client = ctrader_openapi.SpotwareOpenAPIClient(
            client_id="test_id",
            client_secret="test_secret",
            is_live=False
        )
        self.assertEqual(client.host, "demo.ctraderapi.com")
        self.assertEqual(client.port, 5035)

if __name__ == "__main__":
    unittest.main()
