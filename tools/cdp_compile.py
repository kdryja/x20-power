"""Compile (not run) a JS file in Steam's SharedJSContext via CDP and report syntax errors."""
import base64, json, os, socket, sys, urllib.request
from urllib.parse import urlparse

code = open(sys.argv[1]).read().replace("export { index as default };", "")
targets = json.load(urllib.request.urlopen("http://127.0.0.1:8080/json", timeout=5))
ws_url = next(t["webSocketDebuggerUrl"] for t in targets if t.get("title") == "SharedJSContext")
u = urlparse(ws_url)
s = socket.create_connection((u.hostname, u.port), timeout=10)
key = base64.b64encode(os.urandom(16)).decode()
s.sendall((f"GET {u.path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
           f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
resp = b""
while b"\r\n\r\n" not in resp:
    resp += s.recv(4096)
assert b" 101 " in resp.split(b"\r\n")[0], resp[:200]
buf = resp.split(b"\r\n\r\n", 1)[1]

def send(obj):
    data = json.dumps(obj).encode(); mask = os.urandom(4); n = len(data)
    hdr = bytes([0x81]) + (bytes([0x80 | n]) if n < 126 else bytes([0x80 | 126]) + n.to_bytes(2, "big") if n < 65536 else bytes([0x80 | 127]) + n.to_bytes(8, "big"))
    s.sendall(hdr + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

def recv_exact(n):
    global buf
    while len(buf) < n:
        buf += s.recv(65536)
    out, buf = buf[:n], buf[n:]
    return out

def recv():
    b0, b1 = recv_exact(2); n = b1 & 0x7F
    if n == 126: n = int.from_bytes(recv_exact(2), "big")
    elif n == 127: n = int.from_bytes(recv_exact(8), "big")
    return json.loads(recv_exact(n))

send({"id": 0, "method": "Runtime.enable"})
send({"id": 1, "method": "Runtime.compileScript",
      "params": {"expression": code, "sourceURL": "x20-power-check.js", "persistScript": False}})
while True:
    msg = recv()
    if msg.get("id") == 1:
        break
ex = msg.get("result", {}).get("exceptionDetails")
if ex:
    print("SYNTAX ERROR:", ex.get("exception", {}).get("description", ex.get("text")), "line", ex.get("lineNumber", 0) + 1, "col", ex.get("columnNumber"))
    sys.exit(1)
print("compiles OK" if "result" in msg else f"unexpected: {msg}")
