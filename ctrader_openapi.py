import os
import sys
import ssl
import socket
import struct
import threading
import time
import logging
from typing import Dict, Any, Optional, Tuple, List
from collections import deque

logger = logging.getLogger("TradeTalk.cTraderOpenAPI")

# Payload Types according to Spotware Open API 2.0 Specifications
PAYLOAD_PROTO_PING_REQ = 50
PAYLOAD_PROTO_PING_RES = 51
PAYLOAD_PROTO_OA_APPLICATION_AUTH_REQ = 2100
PAYLOAD_PROTO_OA_APPLICATION_AUTH_RES = 2101
PAYLOAD_PROTO_OA_ACCOUNT_AUTH_REQ = 2102
PAYLOAD_PROTO_OA_ACCOUNT_AUTH_RES = 2103
PAYLOAD_PROTO_OA_VERSION_REQ = 2104
PAYLOAD_PROTO_OA_VERSION_RES = 2105
PAYLOAD_PROTO_OA_NEW_ORDER_REQ = 2106
PAYLOAD_PROTO_OA_TRAILING_SL_CHANGED_EVENT = 2107
PAYLOAD_PROTO_OA_CANCEL_ORDER_REQ = 2108
PAYLOAD_PROTO_OA_AMEND_ORDER_REQ = 2109
PAYLOAD_PROTO_OA_AMEND_POSITION_SLTP_REQ = 2110
PAYLOAD_PROTO_OA_CLOSE_POSITION_REQ = 2111
PAYLOAD_PROTO_OA_ASSET_LIST_REQ = 2112
PAYLOAD_PROTO_OA_ASSET_LIST_RES = 2113
PAYLOAD_PROTO_OA_SYMBOLS_LIST_REQ = 2114
PAYLOAD_PROTO_OA_SYMBOLS_LIST_RES = 2115
PAYLOAD_PROTO_OA_SYMBOL_BY_ID_REQ = 2116
PAYLOAD_PROTO_OA_SYMBOL_BY_ID_RES = 2117
PAYLOAD_PROTO_OA_GET_TRENDBARS_REQ = 2118
PAYLOAD_PROTO_OA_GET_TRENDBARS_RES = 2119
PAYLOAD_PROTO_OA_RECONCILE_REQ = 2124
PAYLOAD_PROTO_OA_RECONCILE_RES = 2125
PAYLOAD_PROTO_OA_EXECUTION_EVENT = 2126
PAYLOAD_PROTO_OA_SUBSCRIBE_SPOTS_REQ = 2127
PAYLOAD_PROTO_OA_SUBSCRIBE_SPOTS_RES = 2128
PAYLOAD_PROTO_OA_UNSUBSCRIBE_SPOTS_REQ = 2129
PAYLOAD_PROTO_OA_UNSUBSCRIBE_SPOTS_RES = 2130
PAYLOAD_PROTO_OA_SPOT_EVENT = 2131
PAYLOAD_PROTO_OA_ORDER_ERROR_EVENT = 2132
PAYLOAD_PROTO_OA_ERROR_RES = 2142
PAYLOAD_PROTO_OA_GET_TICKDATA_REQ = 2145
PAYLOAD_PROTO_OA_GET_TICKDATA_RES = 2146
PAYLOAD_PROTO_OA_GET_ACCOUNTS_BY_TOKEN_REQ = 2149
PAYLOAD_PROTO_OA_GET_ACCOUNTS_BY_TOKEN_RES = 2150

# Trendbar Period Mapping (ProtoOATrendbarPeriod enum)
TRENDBAR_PERIOD_MAP = {
    "M1": 1,
    "M2": 2,
    "M3": 3,
    "M4": 4,
    "M5": 5,
    "M10": 6,
    "M15": 7,
    "M30": 8,
    "H1": 9,
    "H4": 10,
    "H12": 11,
    "D1": 12,
    "W1": 13,
    "MN1": 14
}

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
    body.extend(enc_field_int(1, payload_type))
    body.extend(enc_field_bytes(2, payload_bytes))
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


class OpenAPIRateLimiter:
    """
    Token Bucket Rate Limiter enforcing cTrader Open API limits:
    - 50 requests/sec for non-historical messages.
    - 5 requests/sec for historical data (trendbars/tickdata).
    """
    def __init__(self, max_normal_rate: int = 45, max_historical_rate: int = 4):
        self.max_normal = max_normal_rate
        self.max_historical = max_historical_rate
        self._normal_tokens = max_normal_rate
        self._historical_tokens = max_historical_rate
        self._last_refill = time.time()
        self._lock = threading.Lock()

    def acquire(self, is_historical: bool = False):
        with self._lock:
            now = time.time()
            elapsed = now - self._last_refill
            if elapsed >= 1.0:
                self._normal_tokens = self.max_normal
                self._historical_tokens = self.max_historical
                self._last_refill = now

            if is_historical:
                if self._historical_tokens <= 0:
                    sleep_time = max(0.1, 1.0 - (now - self._last_refill))
                    time.sleep(sleep_time)
                    self._historical_tokens = self.max_historical
                    self._last_refill = time.time()
                self._historical_tokens -= 1
            else:
                if self._normal_tokens <= 0:
                    sleep_time = max(0.02, 1.0 - (now - self._last_refill))
                    time.sleep(sleep_time)
                    self._normal_tokens = self.max_normal
                    self._last_refill = time.time()
                self._normal_tokens -= 1


class SpotwareOpenAPIClient:
    """
    Spotware cTrader Open API 2.0 TLS Client with connection monitoring,
    dynamic symbol discovery, rate limiting, and protobuf streaming.
    """
    
    def __init__(
        self,
        client_id: str = "",
        client_secret: str = "",
        is_live: bool = False,
        timeout: int = 8
    ):
        from app.services.credential_store import credential_store
        self.client_id = client_id.strip() if client_id else credential_store.get_secret("CTRADER_CLIENT_ID", "")
        self.client_secret = client_secret.strip() if client_secret else credential_store.get_secret("CTRADER_CLIENT_SECRET", "")
        self.is_live = is_live
        self.timeout = timeout
        self.host = "live.ctraderapi.com" if is_live else "demo.ctraderapi.com"
        self.port = 5035
        self.socket: Optional[ssl.SSLSocket] = None
        self.is_app_authenticated = False
        self.authenticated_accounts = set()
        self.rate_limiter = OpenAPIRateLimiter()
        self._lock = threading.Lock()
        self.last_error: Optional[str] = None
        self.last_heartbeat: float = time.time()
        self._stop_heartbeat = threading.Event()
        self._heartbeat_thread: Optional[threading.Thread] = None

    def _start_heartbeat_loop(self):
        """Starts autonomous background keepalive ping/pong thread."""
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return
        self._stop_heartbeat.clear()
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_worker, daemon=True, name="cTraderHeartbeatDaemon")
        self._heartbeat_thread.start()

    def _heartbeat_worker(self):
        """Sends ProtoPingReq (50) every 15 seconds over idle TCP connection."""
        while not self._stop_heartbeat.is_set():
            time.sleep(5)
            if not self.socket:
                continue
            if time.time() - self.last_heartbeat >= 15.0:
                try:
                    payload = enc_field_int(1, PAYLOAD_PROTO_PING_REQ) + enc_field_int(2, int(time.time() * 1000))
                    self._send_and_receive(PAYLOAD_PROTO_PING_REQ, payload, "HEARTBEAT_PING")
                except Exception as e:
                    logger.debug(f"Heartbeat error: {e}")

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
                self.last_heartbeat = time.time()
                self._start_heartbeat_loop()
                logger.info(f"Connected to Spotware Open API at {self.host}:{self.port}")
                return True
            except Exception as e:
                self.last_error = f"Socket connection failed: {e}"
                logger.error(self.last_error)
                self.socket = None
                return False

    def close(self):
        """Closes the TLS socket and stops heartbeat."""
        self._stop_heartbeat.set()
        with self._lock:
            if self.socket:
                try:
                    self.socket.close()
                except Exception:
                    pass
                self.socket = None
            self.is_app_authenticated = False
            self.authenticated_accounts.clear()

    def _send_and_receive(
        self,
        payload_type: int,
        payload_bytes: bytes,
        client_msg_id: str = "TRADETALK",
        is_historical: bool = False
    ) -> Optional[Dict[str, Any]]:
        """Frames and sends a ProtoMessage, enforcing rate limits."""
        self.rate_limiter.acquire(is_historical=is_historical)
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
            if msg_length > 2 * 1024 * 1024:  # Safety guard 2MB
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
            self.last_heartbeat = time.time()
            parsed = decode_proto_message(raw_body)
            return parsed
        except Exception as e:
            self.last_error = f"Open API communication error: {e}"
            logger.error(self.last_error)
            self.close()
            return None

    def authenticate_application(self) -> Tuple[bool, str]:
        """Sends ProtoOAApplicationAuthReq (payloadType 2100)."""
        payload = (
            enc_field_int(1, PAYLOAD_PROTO_OA_APPLICATION_AUTH_REQ) +
            enc_field_str(2, self.client_id) +
            enc_field_str(3, self.client_secret)
        )
        res = self._send_and_receive(PAYLOAD_PROTO_OA_APPLICATION_AUTH_REQ, payload, "APP_AUTH")
        
        if not res:
            return False, self.last_error or "No response from Spotware"
            
        ptype = res["payload_type"]
        if ptype == PAYLOAD_PROTO_OA_APPLICATION_AUTH_RES:
            self.is_app_authenticated = True
            return True, "APPLICATION_AUTH_SUCCESS"
        elif ptype == PAYLOAD_PROTO_OA_ERROR_RES:
            fields = decode_proto_fields(res["payload"])
            err_code = fields.get(3, [b""])[0]
            err_desc = fields.get(4, [b""])[0]
            code_str = err_code.decode("utf-8", errors="ignore") if isinstance(err_code, bytes) else str(err_code)
            desc_str = err_desc.decode("utf-8", errors="ignore") if isinstance(err_desc, bytes) else str(err_desc)
            err_msg = f"{code_str}: {desc_str}".strip(": ")
            self.last_error = err_msg
            return False, err_msg
        else:
            return False, f"Unexpected response payloadType: {ptype}"

    def authenticate_account(self, account_id: int, access_token: str) -> Tuple[bool, str]:
        """Sends ProtoOAAccountAuthReq (payloadType 2102)."""
        if not self.is_app_authenticated:
            app_ok, app_msg = self.authenticate_application()
            if not app_ok:
                return False, f"Application Auth failed: {app_msg}"
                
        payload = (
            enc_field_int(1, PAYLOAD_PROTO_OA_ACCOUNT_AUTH_REQ) +
            enc_field_int(2, int(account_id)) +
            enc_field_str(3, access_token)
        )
        res = self._send_and_receive(PAYLOAD_PROTO_OA_ACCOUNT_AUTH_REQ, payload, "ACC_AUTH")
        
        if not res:
            return False, self.last_error or "No response from Spotware"
            
        ptype = res["payload_type"]
        if ptype == PAYLOAD_PROTO_OA_ACCOUNT_AUTH_RES:
            self.authenticated_accounts.add(int(account_id))
            return True, "ACCOUNT_AUTH_SUCCESS"
        elif ptype == PAYLOAD_PROTO_OA_ERROR_RES:
            fields = decode_proto_fields(res["payload"])
            err_code = fields.get(3, [b""])[0]
            err_desc = fields.get(4, [b""])[0]
            code_str = err_code.decode("utf-8", errors="ignore") if isinstance(err_code, bytes) else str(err_code)
            desc_str = err_desc.decode("utf-8", errors="ignore") if isinstance(err_desc, bytes) else str(err_desc)
            err_msg = f"{code_str}: {desc_str}".strip(": ")
            self.last_error = err_msg
            return False, err_msg
        else:
            return False, f"Unexpected response payloadType: {ptype}"

    def get_accounts_by_token(self, access_token: str) -> List[Dict[str, Any]]:
        """
        Sends ProtoOAGetAccountListByTokenReq (payloadType 2149) to discover all accounts for the token.
        """
        if not self.is_app_authenticated:
            self.authenticate_application()

        payload = (
            enc_field_int(1, PAYLOAD_PROTO_OA_GET_ACCOUNTS_BY_TOKEN_REQ) +
            enc_field_str(2, access_token)
        )
        res = self._send_and_receive(PAYLOAD_PROTO_OA_GET_ACCOUNTS_BY_TOKEN_REQ, payload, "GET_ACCOUNTS")
        if not res or res["payload_type"] != PAYLOAD_PROTO_OA_GET_ACCOUNTS_BY_TOKEN_RES:
            return []

        fields = decode_proto_fields(res["payload"])
        raw_accounts = fields.get(2, []) # repeated ProtoOACtidTraderAccount
        account_list = []
        for acc_bytes in raw_accounts:
            if isinstance(acc_bytes, bytes):
                acc_fields = decode_proto_fields(acc_bytes)
                acc_id = acc_fields.get(1, [0])[0]
                is_live = bool(acc_fields.get(2, [0])[0])
                account_list.append({
                    "account_id": str(acc_id),
                    "is_live": is_live,
                    "account_type": "LIVE" if is_live else "DEMO",
                    "broker": "cTrader Spotware"
                })
        return account_list

    def get_symbols_list(self, account_id: int) -> List[Dict[str, Any]]:
        """Sends ProtoOASymbolsListReq (payloadType 2114)."""
        payload = (
            enc_field_int(1, PAYLOAD_PROTO_OA_SYMBOLS_LIST_REQ) +
            enc_field_int(2, int(account_id))
        )
        res = self._send_and_receive(PAYLOAD_PROTO_OA_SYMBOLS_LIST_REQ, payload, "SYM_LIST")
        if not res or res["payload_type"] != PAYLOAD_PROTO_OA_SYMBOLS_LIST_RES:
            return []

        fields = decode_proto_fields(res["payload"])
        raw_symbols = fields.get(2, [])
        symbols = []
        for s_bytes in raw_symbols:
            if isinstance(s_bytes, bytes):
                sf = decode_proto_fields(s_bytes)
                sym_id = sf.get(1, [0])[0]
                name = sf.get(2, [b""])[0].decode("utf-8", errors="ignore") if isinstance(sf.get(2, [b""])[0], bytes) else str(sf.get(2, [""])[0])
                digits = sf.get(4, [2])[0]
                pip_position = sf.get(5, [2])[0]
                symbols.append({
                    "symbol_id": sym_id,
                    "name": name,
                    "digits": digits,
                    "pip_position": pip_position
                })
        return symbols

    def subscribe_spots(self, account_id: int, symbol_ids: List[int]) -> bool:
        """Sends ProtoOASubscribeSpotsReq (payloadType 2104)."""
        payload = bytearray()
        payload.extend(enc_field_int(1, PAYLOAD_PROTO_OA_SUBSCRIBE_SPOTS_REQ))
        payload.extend(enc_field_int(2, int(account_id)))
        for sid in symbol_ids:
            payload.extend(enc_field_int(3, int(sid)))

        res = self._send_and_receive(PAYLOAD_PROTO_OA_SUBSCRIBE_SPOTS_REQ, bytes(payload), "SUB_SPOTS")
        return bool(res and res["payload_type"] == PAYLOAD_PROTO_OA_SUBSCRIBE_SPOTS_RES)

    def get_trendbars(
        self,
        account_id: int,
        symbol_id: int,
        timeframe: str = "15m",
        count: int = 50,
        to_timestamp: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Sends ProtoOAGetTrendbarsReq (payloadType 2118)."""
        period_val = TRENDBAR_PERIOD_MAP.get(timeframe.upper().replace(" ", ""), 7) # Default M15
        to_ts = to_timestamp or int(time.time() * 1000)
        from_ts = to_ts - (count * 60 * 15 * 1000)

        payload = bytearray()
        payload.extend(enc_field_int(1, PAYLOAD_PROTO_OA_GET_TRENDBARS_REQ))
        payload.extend(enc_field_int(2, int(account_id)))
        payload.extend(enc_field_int(3, from_ts))
        payload.extend(enc_field_int(4, to_ts))
        payload.extend(enc_field_int(5, period_val))
        payload.extend(enc_field_int(6, int(symbol_id)))
        payload.extend(enc_field_int(7, int(count)))

        res = self._send_and_receive(PAYLOAD_PROTO_OA_GET_TRENDBARS_REQ, bytes(payload), "GET_BARS", is_historical=True)
        if not res or res["payload_type"] != PAYLOAD_PROTO_OA_GET_TRENDBARS_RES:
            return []

        fields = decode_proto_fields(res["payload"])
        raw_bars = fields.get(7, []) # repeated ProtoOATrendbar
        candles = []
        for b_bytes in raw_bars:
            if isinstance(b_bytes, bytes):
                bf = decode_proto_fields(b_bytes)
                vol = bf.get(1, [0])[0]
                low = bf.get(3, [0])[0] / 100000.0
                open_delta = bf.get(4, [0])[0] / 100000.0
                high_delta = bf.get(5, [0])[0] / 100000.0
                close_delta = bf.get(6, [0])[0] / 100000.0
                ts = bf.get(7, [0])[0]
                candles.append({
                    "timestamp": ts,
                    "open": round(low + open_delta, 5),
                    "high": round(low + high_delta, 5),
                    "low": round(low, 5),
                    "close": round(low + close_delta, 5),
                    "volume": vol
                })
        return candles

    def send_market_order(
        self,
        account_id: int,
        symbol_id: int,
        trade_side: str,  # "BUY" or "SELL"
        volume: int,      # broker units (e.g. 100 for 0.01 lot Gold)
        sl_price: float,
        tp_price: float,
        comment: str = "TradeTalk AI Server Execution"
    ) -> Dict[str, Any]:
        """Sends ProtoOANewOrderReq (payloadType 2106)."""
        side_val = 1 if trade_side.upper() == "BUY" else 2
        payload = bytearray()
        payload.extend(enc_field_int(1, PAYLOAD_PROTO_OA_NEW_ORDER_REQ))
        payload.extend(enc_field_int(2, int(account_id)))
        payload.extend(enc_field_int(3, int(symbol_id)))
        payload.extend(enc_field_int(4, 1)) # MARKET
        payload.extend(enc_field_int(5, side_val))
        payload.extend(enc_field_int(6, int(volume)))
        if sl_price > 0:
            payload.extend(enc_field_double(11, float(sl_price)))
        if tp_price > 0:
            payload.extend(enc_field_double(12, float(tp_price)))
        if comment:
            payload.extend(enc_field_str(14, comment[:50]))
            
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
