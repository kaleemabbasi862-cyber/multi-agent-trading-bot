import os
import sys
import ssl
import socket
import struct
import threading
import time
import logging
from typing import Dict, Any, Optional, Tuple, List

logger = logging.getLogger("TradeTalk.cTraderOpenAPI")

# Payload Types according to Spotware Open API 2.0 Specifications
PAYLOAD_PROTO_PING_REQ = 50
PAYLOAD_PROTO_PING_RES = 51
PAYLOAD_PROTO_OA_APPLICATION_AUTH_REQ = 2100
PAYLOAD_PROTO_OA_APPLICATION_AUTH_RES = 2101
PAYLOAD_PROTO_OA_ACCOUNT_AUTH_REQ = 2102
PAYLOAD_PROTO_OA_ACCOUNT_AUTH_RES = 2103
PAYLOAD_PROTO_OA_SYMBOLS_LIST_REQ = 2114
PAYLOAD_PROTO_OA_SYMBOLS_LIST_RES = 2115
PAYLOAD_PROTO_OA_NEW_ORDER_REQ = 2106
PAYLOAD_PROTO_OA_EXECUTION_EVENT = 2126
PAYLOAD_PROTO_OA_CANCEL_ORDER_REQ = 2108
PAYLOAD_PROTO_OA_CLOSE_POSITION_REQ = 2110
PAYLOAD_PROTO_OA_RECONCILE_REQ = 2124
PAYLOAD_PROTO_OA_RECONCILE_RES = 2125
PAYLOAD_PROTO_OA_ORDER_ERROR_EVENT = 2132
PAYLOAD_PROTO_OA_ERROR_RES = 2142
PAYLOAD_PROTO_OA_GET_ACCOUNTS_BY_TOKEN_REQ = 2149
PAYLOAD_PROTO_OA_GET_ACCOUNTS_BY_TOKEN_RES = 2150

# Wire Types
WIRE_VARINT = 0
WIRE_64BIT = 1
WIRE_LENGTH_DELIMITED = 2
WIRE_32BIT = 5

def encode_varint(value: int) -> bytes:
    """Encodes an integer into standard protobuf varint bytes."""
    buf = bytearray()
    if value < 0:
        value = (1 << 64) + value
    while value > 0x7F:
        buf.append((value & 0x7F) | 0x80)
        value >>= 7
    buf.append(value & 0x7F)
    return bytes(buf)

def decode_varint(buffer: bytes, offset: int = 0) -> Tuple[int, int]:
    """Decodes a varint from buffer starting at offset. Returns (value, new_offset)."""
    result = 0
    shift = 0
    while offset < len(buffer):
        byte = buffer[offset]
        offset += 1
        result |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            break
        shift += 7
    return result, offset

def enc_field_int(field_number: int, value: int) -> bytes:
    tag = (field_number << 3) | WIRE_VARINT
    return encode_varint(tag) + encode_varint(value)

def enc_field_str(field_number: int, value: str) -> bytes:
    tag = (field_number << 3) | WIRE_LENGTH_DELIMITED
    val_bytes = value.encode("utf-8")
    return encode_varint(tag) + encode_varint(len(val_bytes)) + val_bytes

def enc_field_bytes(field_number: int, value: bytes) -> bytes:
    tag = (field_number << 3) | WIRE_LENGTH_DELIMITED
    return encode_varint(tag) + encode_varint(len(value)) + value

def enc_field_double(field_number: int, value: float) -> bytes:
    tag = (field_number << 3) | WIRE_64BIT
    return encode_varint(tag) + struct.pack("<d", float(value))

def enc_proto_message(payload_type: int, payload_bytes: bytes, client_msg_id: Optional[str] = None) -> bytes:
    """Encodes a ProtoMessage wrapper with 4-byte length prefix."""
    body = bytearray()
    # field 1: payloadType (uint32)
    body.extend(enc_field_int(1, payload_type))
    # field 2: payload (bytes)
    body.extend(enc_field_bytes(2, payload_bytes))
    # field 3: clientMsgId (string, optional)
    if client_msg_id:
        body.extend(enc_field_str(3, client_msg_id))
    
    length_prefix = struct.pack(">I", len(body))
    return length_prefix + bytes(body)

def decode_proto_fields(buf: bytes) -> Dict[int, List[Any]]:
    """Decodes raw protobuf fields into a dictionary mapping field_number -> [values]."""
    offset = 0
    fields: Dict[int, List[Any]] = {}
    buf_len = len(buf)
    
    while offset < buf_len:
        tag, offset = decode_varint(buf, offset)
        field_num = tag >> 3
        wire_type = tag & 0x07
        
        if wire_type == WIRE_VARINT:
            val, offset = decode_varint(buf, offset)
            fields.setdefault(field_num, []).append(val)
        elif wire_type == WIRE_64BIT:
            if offset + 8 <= buf_len:
                val = struct.unpack("<d", buf[offset:offset+8])[0]
                offset += 8
                fields.setdefault(field_num, []).append(val)
        elif wire_type == WIRE_LENGTH_DELIMITED:
            length, offset = decode_varint(buf, offset)
            val = buf[offset:offset+length]
            offset += length
            fields.setdefault(field_num, []).append(val)
        elif wire_type == WIRE_32BIT:
            if offset + 4 <= buf_len:
                val = struct.unpack("<f", buf[offset:offset+4])[0]
                offset += 4
                fields.setdefault(field_num, []).append(val)
        else:
            break
    return fields

def decode_proto_message(raw_msg_bytes: bytes) -> Dict[str, Any]:
    """Decodes a top-level ProtoMessage."""
    fields = decode_proto_fields(raw_msg_bytes)
    payload_type = fields.get(1, [0])[0]
    payload = fields.get(2, [b""])[0]
    client_msg_id = ""
    if 3 in fields and fields[3]:
        try:
            client_msg_id = fields[3][0].decode("utf-8", errors="ignore")
        except Exception:
            pass
            
    return {
        "payload_type": payload_type,
        "payload": payload,
        "client_msg_id": client_msg_id
    }


class SpotwareOpenAPIClient:
    """
    Spotware cTrader Open API 2.0 TLS Client.
    Connects directly to Spotware Cloud infrastructure (demo.ctraderapi.com:5035 / live.ctraderapi.com:5035).
    """
    
    def __init__(
        self,
        client_id: str = "",
        client_secret: str = "",
        is_live: bool = False,
        timeout: int = 8
    ):
        self.client_id = client_id.strip() if client_id else os.getenv("CTRADER_CLIENT_ID", "").strip('"')
        self.client_secret = client_secret.strip() if client_secret else os.getenv("CTRADER_CLIENT_SECRET", "").strip('"')
        self.is_live = is_live
        self.timeout = timeout
        self.host = "live.ctraderapi.com" if is_live else "demo.ctraderapi.com"
        self.port = 5035
        self.socket: Optional[ssl.SSLSocket] = None
        self.is_app_authenticated = False
        self.authenticated_accounts = set()
        self._lock = threading.Lock()
        self.last_error: Optional[str] = None

    def connect(self) -> bool:
        """Establishes TLS TCP socket connection with Spotware Open API."""
        with self._lock:
            try:
                if self.socket:
                    try:
                        self.socket.close()
                    except Exception:
                        pass
                
                raw_sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
                ctx = ssl.create_default_context()
                self.socket = ctx.wrap_socket(raw_sock, server_hostname=self.host)
                logger.info(f"Connected to Spotware Open API at {self.host}:{self.port}")
                return True
            except Exception as e:
                self.last_error = f"Socket connection failed: {e}"
                logger.error(self.last_error)
                self.socket = None
                return False

    def close(self):
        """Closes the TLS socket."""
        with self._lock:
            if self.socket:
                try:
                    self.socket.close()
                except Exception:
                    pass
                self.socket = None
            self.is_app_authenticated = False

    def _send_and_receive(self, payload_type: int, payload_bytes: bytes, client_msg_id: str = "TRADETALK") -> Optional[Dict[str, Any]]:
        """Frames and sends a ProtoMessage, then reads response."""
        if not self.socket:
            if not self.connect():
                return None
                
        msg = enc_proto_message(payload_type, payload_bytes, client_msg_id)
        try:
            self.socket.sendall(msg)
            
            # Read 4-byte length prefix
            len_bytes = self.socket.recv(4)
            if not len_bytes or len(len_bytes) < 4:
                self.last_error = "Connection closed by broker during length prefix read"
                return None
            
            msg_length = struct.unpack(">I", len_bytes)[0]
            if msg_length > 1024 * 1024:  # Safety guard 1MB
                self.last_error = f"Message size excessive: {msg_length}"
                return None
            
            # Read full body
            chunks = []
            bytes_read = 0
            while bytes_read < msg_length:
                chunk = self.socket.recv(min(msg_length - bytes_read, 4096))
                if not chunk:
                    break
                chunks.append(chunk)
                bytes_read += len(chunk)
                
            raw_body = b"".join(chunks)
            parsed = decode_proto_message(raw_body)
            return parsed
        except Exception as e:
            self.last_error = f"Open API communication error: {e}"
            logger.error(self.last_error)
            self.close()
            return None

    def authenticate_application(self) -> Tuple[bool, str]:
        """
        Sends ProtoOAApplicationAuthReq (payloadType 2100).
        """
        # ProtoOAApplicationAuthReq: field 1: clientId, field 2: clientSecret
        payload = enc_field_str(1, self.client_id) + enc_field_str(2, self.client_secret)
        res = self._send_and_receive(PAYLOAD_PROTO_OA_APPLICATION_AUTH_REQ, payload, "APP_AUTH")
        
        if not res:
            return False, self.last_error or "No response from Spotware"
            
        ptype = res["payload_type"]
        if ptype == PAYLOAD_PROTO_OA_APPLICATION_AUTH_RES:
            self.is_app_authenticated = True
            return True, "APPLICATION_AUTH_SUCCESS"
        elif ptype == PAYLOAD_PROTO_OA_ERROR_RES:
            fields = decode_proto_fields(res["payload"])
            err_code = fields.get(1, [b""])[0]
            err_desc = fields.get(2, [b""])[0]
            code_str = err_code.decode("utf-8", errors="ignore") if isinstance(err_code, bytes) else str(err_code)
            desc_str = err_desc.decode("utf-8", errors="ignore") if isinstance(err_desc, bytes) else str(err_desc)
            err_msg = f"{code_str}: {desc_str}".strip(": ")
            self.last_error = err_msg
            return False, err_msg
        else:
            return False, f"Unexpected response payloadType: {ptype}"

    def authenticate_account(self, account_id: int, access_token: str) -> Tuple[bool, str]:
        """
        Sends ProtoOAAccountAuthReq (payloadType 2102).
        """
        if not self.is_app_authenticated:
            app_ok, app_msg = self.authenticate_application()
            if not app_ok:
                return False, f"Application Auth failed: {app_msg}"
                
        # ProtoOAAccountAuthReq: field 1: ctidTraderAccountId (int64), field 2: accessToken (string)
        payload = enc_field_int(1, int(account_id)) + enc_field_str(2, access_token)
        res = self._send_and_receive(PAYLOAD_PROTO_OA_ACCOUNT_AUTH_REQ, payload, "ACC_AUTH")
        
        if not res:
            return False, self.last_error or "No response from Spotware"
            
        ptype = res["payload_type"]
        if ptype == PAYLOAD_PROTO_OA_ACCOUNT_AUTH_RES:
            self.authenticated_accounts.add(int(account_id))
            return True, "ACCOUNT_AUTH_SUCCESS"
        elif ptype == PAYLOAD_PROTO_OA_ERROR_RES:
            fields = decode_proto_fields(res["payload"])
            err_code = fields.get(1, [b""])[0]
            err_desc = fields.get(2, [b""])[0]
            code_str = err_code.decode("utf-8", errors="ignore") if isinstance(err_code, bytes) else str(err_code)
            desc_str = err_desc.decode("utf-8", errors="ignore") if isinstance(err_desc, bytes) else str(err_desc)
            err_msg = f"{code_str}: {desc_str}".strip(": ")
            self.last_error = err_msg
            return False, err_msg
        else:
            return False, f"Unexpected response payloadType: {ptype}"

    def send_market_order(
        self,
        account_id: int,
        symbol_id: int,
        trade_side: str,  # "BUY" or "SELL"
        volume: int,      # in broker volume units (e.g. 100 for 0.01 lot Gold)
        sl_price: float,
        tp_price: float,
        comment: str = "TradeTalk AI Server Execution"
    ) -> Dict[str, Any]:
        """
        Sends ProtoOANewOrderReq (payloadType 2106).
        """
        side_val = 1 if trade_side.upper() == "BUY" else 2
        
        # ProtoOANewOrderReq fields:
        # 1: ctidTraderAccountId (int64)
        # 2: symbolId (int64)
        # 3: orderType (1 = MARKET)
        # 4: tradeSide (1 = BUY, 2 = SELL)
        # 5: volume (int64)
        # 10: stopLoss (double)
        # 11: takeProfit (double)
        # 13: comment (string)
        payload = bytearray()
        payload.extend(enc_field_int(1, int(account_id)))
        payload.extend(enc_field_int(2, int(symbol_id)))
        payload.extend(enc_field_int(3, 1)) # MARKET
        payload.extend(enc_field_int(4, side_val))
        payload.extend(enc_field_int(5, int(volume)))
        if sl_price > 0:
            payload.extend(enc_field_double(10, float(sl_price)))
        if tp_price > 0:
            payload.extend(enc_field_double(11, float(tp_price)))
        if comment:
            payload.extend(enc_field_str(13, comment[:50]))
            
        res = self._send_and_receive(PAYLOAD_PROTO_OA_NEW_ORDER_REQ, bytes(payload), f"ORD_{int(time.time())}")
        
        if not res:
            return {"status": "ERROR_NO_RESPONSE", "error": self.last_error or "No response from Spotware"}
            
        ptype = res["payload_type"]
        if ptype == PAYLOAD_PROTO_OA_EXECUTION_EVENT:
            fields = decode_proto_fields(res["payload"])
            order_id = fields.get(2, [0])[0] if 2 in fields else None
            pos_id = fields.get(3, [0])[0] if 3 in fields else None
            exec_price = fields.get(10, [0.0])[0] if 10 in fields else None
            return {
                "status": "SUCCESS",
                "payload_type": ptype,
                "order_id": order_id,
                "position_id": pos_id,
                "execution_price": exec_price,
                "raw_fields": str(fields)
            }
        elif ptype in (PAYLOAD_PROTO_OA_ORDER_ERROR_EVENT, PAYLOAD_PROTO_OA_ERROR_RES):
            fields = decode_proto_fields(res["payload"])
            err_code = fields.get(1, [b""])[0]
            err_desc = fields.get(2, [b""])[0]
            code_str = err_code.decode("utf-8", errors="ignore") if isinstance(err_code, bytes) else str(err_code)
            desc_str = err_desc.decode("utf-8", errors="ignore") if isinstance(err_desc, bytes) else str(err_desc)
            return {
                "status": "ERROR_BROKER_REJECTED",
                "error_code": code_str,
                "error_description": desc_str
            }
        else:
            return {
                "status": "ERROR_UNEXPECTED_PAYLOAD",
                "payload_type": ptype
            }
