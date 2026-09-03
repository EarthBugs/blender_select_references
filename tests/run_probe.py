# -*- coding: utf-8 -*-
"""通用 socket 发送器：把指定文件内容经 Blender MCP socket(5001) 发送执行，
打印返回的 result JSON（带超时，绝不挂起）。

用法：
  python tests/run_probe.py <要发送的 Blender 侧脚本路径>
"""
import socket
import json
import time
import sys

HOST, PORT = "127.0.0.1", 5001
RECV_TIMEOUT = 60


def main(path):
    with open(path, "r", encoding="utf-8") as f:
        code = f.read()
    payload = json.dumps(
        {"type": "execute", "code": code, "strict_json": True}
    ).encode("utf-8") + b"\0"
    s = socket.create_connection((HOST, PORT), timeout=5)
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
    if resp.get("status") == "error":
        print("socket error:", resp.get("message", "")[:4000])
        sys.exit(3)
    print(json.dumps(resp.get("result", {}), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main(sys.argv[1])
