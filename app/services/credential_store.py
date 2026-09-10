import os
import sys
import base64
import json
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger("TradeTalk.Security.CredentialStore")

# Check if running on Windows for DPAPI support
_IS_WINDOWS = sys.platform == "win32"

if _IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_byte))
        ]

    _CryptProtectData = ctypes.windll.crypt32.CryptProtectData
    _CryptProtectData.argtypes = [
        ctypes.POINTER(DATA_BLOB),
        wintypes.LPCWSTR,
        ctypes.POINTER(DATA_BLOB),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(DATA_BLOB)
    ]
    _CryptProtectData.restype = wintypes.BOOL

    _CryptUnprotectData = ctypes.windll.crypt32.CryptUnprotectData
    _CryptUnprotectData.argtypes = [
        ctypes.POINTER(DATA_BLOB),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(DATA_BLOB),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(DATA_BLOB)
    ]
    _CryptUnprotectData.restype = wintypes.BOOL

    _LocalFree = ctypes.windll.kernel32.LocalFree
    _LocalFree.argtypes = [ctypes.c_void_p]
    _LocalFree.restype = ctypes.c_void_p


def dpapi_encrypt(plaintext: str) -> str:
    """Encrypts plaintext string using Windows DPAPI (tied to current Windows user)."""
    if not plaintext:
        return ""
    if not _IS_WINDOWS:
        # Fallback obfuscation for non-Windows dev environments
        return "B64:" + base64.b64encode(plaintext.encode("utf-8")).decode("utf-8")

    data = plaintext.encode("utf-8")
    data_in = DATA_BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data, len(data)), ctypes.POINTER(ctypes.c_byte)))
    data_out = DATA_BLOB()

    # CRYPTPROTECT_UI_FORBIDDEN = 0x1
    if _CryptProtectData(ctypes.byref(data_in), "TradeTalk Secret", None, None, None, 0x1, ctypes.byref(data_out)):
        try:
            encrypted_bytes = ctypes.string_at(data_out.pbData, data_out.cbData)
            return "DPAPI:" + base64.b64encode(encrypted_bytes).decode("utf-8")
        finally:
            _LocalFree(data_out.pbData)
    else:
        raise RuntimeError("Windows DPAPI encryption failed")


def dpapi_decrypt(encrypted_str: str) -> str:
    """Decrypts DPAPI-encrypted string using Windows DPAPI."""
    if not encrypted_str:
        return ""
    
    if encrypted_str.startswith("B64:"):
        return base64.b64decode(encrypted_str[4:].encode("utf-8")).decode("utf-8")

    if not encrypted_str.startswith("DPAPI:"):
        # Plaintext or unknown format
        return encrypted_str

    if not _IS_WINDOWS:
        return ""

    raw_cipher = base64.b64decode(encrypted_str[6:].encode("utf-8"))
    data_in = DATA_BLOB(len(raw_cipher), ctypes.cast(ctypes.create_string_buffer(raw_cipher, len(raw_cipher)), ctypes.POINTER(ctypes.c_byte)))
    data_out = DATA_BLOB()

    if _CryptUnprotectData(ctypes.byref(data_in), None, None, None, None, 0x1, ctypes.byref(data_out)):
        try:
            decrypted_bytes = ctypes.string_at(data_out.pbData, data_out.cbData)
            return decrypted_bytes.decode("utf-8")
        finally:
            _LocalFree(data_out.pbData)
    else:
        raise RuntimeError("Windows DPAPI decryption failed")


class CredentialStore:
    """
    Secure Credential Store for storing API keys, OAuth tokens, and secrets.
    Persists encrypted values to a local secure storage file.
    """
    def __init__(self, storage_path: Optional[str] = None):
        if storage_path is None:
            from app.config import settings
            base_dir = os.path.dirname(settings.DATABASE_PATH)
            storage_path = os.path.join(base_dir, "secure_vault.enc")
        self.storage_path = storage_path
        self._memory_cache: Dict[str, str] = {}
        self._load_vault()

    def _load_vault(self):
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    encrypted_data = json.load(f)
                for k, v in encrypted_data.items():
                    try:
                        self._memory_cache[k] = dpapi_decrypt(v)
                    except Exception as e:
                        logger.warning(f"Failed to decrypt vault key '{k}': {e}")
            except Exception as e:
                logger.error(f"Error loading secure vault: {e}")

    def _save_vault(self):
        try:
            encrypted_data = {}
            for k, v in self._memory_cache.items():
                if v:
                    encrypted_data[k] = dpapi_encrypt(v)
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(encrypted_data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving secure vault: {e}")

    def set_secret(self, key: str, value: str):
        """Stores a secret securely in the vault."""
        self._memory_cache[key] = value
        self._save_vault()

    def get_secret(self, key: str, default: str = "") -> str:
        """Retrieves and decrypts a secret from the vault."""
        if key in self._memory_cache and self._memory_cache[key]:
            return self._memory_cache[key]
        # Fallback to environment variables
        env_val = os.getenv(key, "")
        if env_val:
            return env_val.strip('"').strip()
        return default

    def mask_secret(self, key: str) -> str:
        """Returns a masked representation (e.g. '38205_...PNT') for safe UI display."""
        val = self.get_secret(key)
        if not val or len(val) <= 8:
            return "********" if val else ""
        return f"{val[:6]}...{val[-4:]}"

    def is_kill_switch_active(self) -> bool:
        """Returns True if Emergency Kill Switch is active."""
        from app.config import settings
        return bool(getattr(settings, "EMERGENCY_KILL_SWITCH_ACTIVE", False))

    def set_kill_switch(self, active: bool):
        """Sets the Emergency Kill Switch state."""
        from app.config import settings
        settings.EMERGENCY_KILL_SWITCH_ACTIVE = bool(active)


# Global Credential Store Singleton
credential_store = CredentialStore()
