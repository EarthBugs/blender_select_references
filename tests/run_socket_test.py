# -*- coding: utf-8 -*-
"""把 tests/test_select_references.py 通过 Blender MCP socket(5001) 发送执行，
打印返回的 JSON 结果（带超时，绝不挂起）。"""

import socket
import json
import time
import sys

TEST_FILE = r"C:\Users\EarthBugs\Documents\current_working\20260901_blender_select_references\tests\test_select_references.py"
HOST, PORT = "127.0.0.1", 5001
SEND_TIMEOUT, RECV_TIMEOUT = 5, 60

with open(TEST_FILE, "r", encoding="utf-8") as f:
    code = f.read()

payload = json.dumps({"type": "execute", "code": code, "strict_json": True}).encode("utf-8") + b"\0"

s = socket.create_connection((HOST, PORT), timeout=SEND_TIMEOUT)
s.settimeout(RECV_TIMEOUT)
s.sendall(payload)
buf = bytearray()
start = time.time()
while b"\0" not in buf and time.time() - start < RECV_TIMEOUT:
    try:
        data = s.recv(65536)
    except socket.timeout:
        print("!! recv timeout", file=sys.stderr)
        break
    if not data:
        break
    buf.extend(data)
s.close()

raw = bytes(buf).decode("utf-8", "replace").strip("\0")
if not raw:
    print("!! empty response")
    sys.exit(2)

resp = json.loads(raw)
status = resp.get("status")
print("socket status:", status)
if status == "error":
    print("message:", resp.get("message", "")[:2000])
    sys.exit(3)

r = resp.get("result", {})
print("== env ==", json.dumps(r.get("env", {}), ensure_ascii=False))
print("== summary ==")
print("passed:", r.get("passed"), "failed:", r.get("failed"))
print("env_errors:", json.dumps(r.get("env_errors", []), ensure_ascii=False))
print("== failures ==")
print(json.dumps(r.get("failures", []), ensure_ascii=False, indent=2))
print("== all checks ==")
for c in r.get("all_checks", []):
    print("[{}] {} | expected={} actual={} {}".format(
        "PASS" if c["pass"] else "FAIL", c["name"],
        json.dumps(c["expected"], ensure_ascii=False),
        json.dumps(c["actual"], ensure_ascii=False),
        ("| " + c["note"]) if c.get("note") else ""))
