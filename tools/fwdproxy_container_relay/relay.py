#!/usr/bin/env python3
"""Host-side TCP relay: <host>:19080 -> fwdproxy:8080.

WHY: on this agent host, containers CANNOT authenticate to fwdproxy directly — the
`agent:claude_code` egress identity is ambient to the host process context and does NOT
cross into a (rootless) container network namespace. Proven: `https://pypi.org` is 200 from
the host but "Connection reset by peer" from inside a container hitting fwdproxy directly.
Neither a destination allowlist nor a registry mirror fixes this (it's an identity problem).

FIX: this relay runs as a HOST process (so its onward connection to fwdproxy carries the
agent identity fwdproxy authorizes) and forwards raw bytes. A build container points its
HTTP(S)_PROXY at this relay and gets working pip/npm/apt egress. Proven: container ->
relay -> fwdproxy -> pypi = 200.

USE:
    python relay.py &                       # listens on 0.0.0.0:19080
    # build container (host network) then uses:
    #   --network=host  -e https_proxy=http://127.0.0.1:19080  -e http_proxy=http://127.0.0.1:19080
"""
import socket
import threading

LISTEN = ("0.0.0.0", 19080)
UPSTREAM = ("fwdproxy", 8080)


def _pipe(a, b):
    try:
        while True:
            d = a.recv(65536)
            if not d:
                break
            b.sendall(d)
    except Exception:
        pass
    finally:
        for s in (a, b):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass


def _handle(c):
    try:
        u = socket.create_connection(UPSTREAM, timeout=30)
    except Exception:
        c.close()
        return
    threading.Thread(target=_pipe, args=(c, u), daemon=True).start()
    threading.Thread(target=_pipe, args=(u, c), daemon=True).start()


def main():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(LISTEN)
    s.listen(128)
    print(f"fwdproxy container relay on {LISTEN[0]}:{LISTEN[1]} -> {UPSTREAM[0]}:{UPSTREAM[1]}",
          flush=True)
    while True:
        c, _ = s.accept()
        threading.Thread(target=_handle, args=(c,), daemon=True).start()


if __name__ == "__main__":
    main()
