#!/usr/bin/env python3
"""LLM gateway of changes/0.2.2_math_group_evo_deepseek/compose: the only route from the agents to the model API.

- At most `max_in_flight` requests are in flight upstream (the limit the provider asked us to respect). A request holds
  its slot until its response stream ends. Requests of review sessions go first; see Slots.
- The API key stays here: agent containers get a dummy key and cannot read this one.
- Only POST /v1/responses with the configured model is forwarded.
- Upstream 429 and 5xx are retried here with backoff, outside the slot; a client that went away gives its place up.
- Assistant messages with no text are removed from the history (see drop_empty_assistant).
- Every request is logged (queue wait, latency, tokens) to <log dir>/gateway.jsonl; <log dir>/live.json shows the
  current load. Standard library only.

2.3: copied from changes/0.03_deepseek_verify/scripts/llm_gateway.py; the only change is the listen address, now
from the environment variable GATEWAY_HOST (default 0.0.0.0 as before; 2.3 runs it on the host with 127.0.0.1).

usage: llm_gateway.py <port> <log dir> <key file> <upstream base url> <model> <max in flight> [<main reserved>
       [<upstream model> [<upstream effort>]]]

study_ab: if <upstream model> is given (not "-"), the request's model is replaced by it before forwarding, so the
agents keep seeing <model>; if <upstream effort> is given (not "-"), reasoning.effort is set to it.
"""
import asyncio, collections, json, os, ssl, sys, time
from urllib.parse import urlsplit

PORT, LOGD, KEYF, BASE, MODEL, MAXF = sys.argv[1:7]
PORT, MAXF = int(PORT), int(MAXF)
RESERVE = int(sys.argv[7]) if len(sys.argv) > 7 else 0
UP_MODEL = sys.argv[8] if len(sys.argv) > 8 and sys.argv[8] != "-" else None
UP_EFFORT = sys.argv[9] if len(sys.argv) > 9 and sys.argv[9] != "-" else None
KEY = open(KEYF).read().strip()
UP = urlsplit(BASE)
RETRY_STATUS = {429, 500, 502, 503, 504}
MAX_TRIES = 6
READ_TIMEOUT_S = 1800
FORWARD = {"content-type", "accept", "content-encoding", "user-agent", "originator", "session-id", "thread-id",
           "x-client-request-id"}
stats = {"in_flight": 0, "queued": 0, "peak_in_flight": 0, "served": 0, "started": time.time()}


class Slots:
    """At most `n` requests in flight, first come first served within each kind. Requests of review sessions ("side") go
    before those of main sessions, which keep `reserve` of the slots while any of them waits, so that they never stop.
    A free slot is never left idle: with no main request waiting, reviews may use all the slots, and the other way round."""

    def __init__(self, n, reserve):
        self.n, self.reserve = n, reserve
        self.busy = {"side": 0, "main": 0}
        self.waiting = {"side": collections.deque(), "main": collections.deque()}

    def _grant(self):
        w, busy = self.waiting, self.busy
        while sum(busy.values()) < self.n:
            for q in w.values():
                while q and q[0].done():    # gave up its place
                    q.popleft()
            if w["side"] and (not w["main"] or busy["side"] < self.n - self.reserve):
                kind = "side"
            elif w["main"]:
                kind = "main"
            else:
                return
            busy[kind] += 1
            w[kind].popleft().set_result(None)

    async def acquire(self, kind):
        f = asyncio.get_running_loop().create_future()
        self.waiting[kind].append(f)
        self._grant()
        try:
            await f
        except asyncio.CancelledError:
            if f.done() and not f.cancelled():      # granted in the same instant
                self.release(kind)
            raise

    def release(self, kind):
        self.busy[kind] -= 1
        self._grant()


def record(**kw):
    with open(os.path.join(LOGD, "gateway.jsonl"), "a") as o:
        o.write(json.dumps({"t": round(time.time(), 2), **kw}) + "\n")


def drop_empty_assistant(req, body):
    """The endpoint returns an assistant message with no text next to a tool call, Codex replays it as history, and
    deepseek-v4.1-flash refuses it ("content or tool_calls must be set"). It says nothing, so it is removed here. A
    request without such a message is forwarded byte for byte."""
    items = req.get("input")
    if not isinstance(items, list):
        return body

    def empty(x):
        c = x.get("content") if isinstance(x, dict) else None
        return (isinstance(c, list) and x.get("type") == "message" and x.get("role") == "assistant"
                and all(isinstance(p, dict) and p.get("type") == "output_text" and not p.get("text") for p in c))

    keep = [x for x in items if not empty(x)]
    return body if len(keep) == len(items) else json.dumps({**req, "input": keep}).encode()


async def respond(w, status, payload):
    data = json.dumps(payload).encode()
    w.write(f"HTTP/1.1 {status} Error\r\nContent-Type: application/json\r\nContent-Length: {len(data)}\r\n"
            "Connection: close\r\n\r\n".encode() + data)
    await w.drain()


def scan_sse(buf, usage):
    """Consume complete SSE events from buf; note the usage of `response.completed`. Returns the unconsumed rest."""
    while True:
        i = buf.find(b"\n\n")
        if i < 0:
            return buf
        ev, buf = buf[:i], buf[i + 2:]
        for line in ev.split(b"\n"):
            if line.startswith(b"data:") and b"response.completed" in line:
                try:
                    u = json.loads(line[5:]).get("response", {}).get("usage") or {}
                except ValueError:
                    continue
                usage.update(input=u.get("input_tokens"), output=u.get("output_tokens"),
                             cached=(u.get("input_tokens_details") or {}).get("cached_tokens"),
                             reasoning=(u.get("output_tokens_details") or {}).get("reasoning_tokens"))


async def read_body(r, headers):
    """Yields decoded chunks of an upstream response body (chunked, content-length or close-delimited). A stream that
    stays silent for READ_TIMEOUT_S is dropped: it would hold a slot for ever. The client then retries."""
    te = headers.get("transfer-encoding", "").lower()
    if "chunked" in te:
        while True:
            line = await asyncio.wait_for(r.readline(), READ_TIMEOUT_S)
            if not line:
                raise ConnectionError("the upstream closed the stream")
            n = int(line.split(b";")[0].strip() or b"0", 16)
            if n == 0:
                await r.readline()
                return
            yield await asyncio.wait_for(r.readexactly(n), READ_TIMEOUT_S)
            await asyncio.wait_for(r.readline(), READ_TIMEOUT_S)
    elif "content-length" in headers:
        left = int(headers["content-length"])
        while left > 0:
            d = await asyncio.wait_for(r.read(min(65536, left)), READ_TIMEOUT_S)
            if not d:
                return
            left -= len(d)
            yield d
    else:
        while d := await asyncio.wait_for(r.read(65536), READ_TIMEOUT_S):
            yield d


async def upstream(head_lines, body):
    """Open the upstream connection and send the request; returns (reader, writer, status, headers)."""
    port = UP.port or (443 if UP.scheme == "https" else 80)
    ctx = ssl.create_default_context() if UP.scheme == "https" else None
    ur, uw = await asyncio.wait_for(asyncio.open_connection(UP.hostname, port, ssl=ctx, limit=1 << 22), 60)
    path = UP.path.rstrip("/") + "/responses"
    uw.write(("\r\n".join([f"POST {path} HTTP/1.1", f"Host: {UP.netloc}", f"Authorization: Bearer {KEY}",
                           f"Content-Length: {len(body)}", "Connection: close"] + head_lines) + "\r\n\r\n").encode())
    uw.write(body)
    await uw.drain()
    status = int((await asyncio.wait_for(ur.readline(), READ_TIMEOUT_S)).split()[1])
    h = {}
    while (line := await asyncio.wait_for(ur.readline(), READ_TIMEOUT_S)) not in (b"\r\n", b"\n", b""):
        k, _, v = line.decode("latin-1").partition(":")
        h[k.strip().lower()] = v.strip()
    return ur, uw, status, h


async def serve_one(cr, cw, slots):
    head = await cr.readuntil(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    method, target = lines[0].split()[:2]
    hdr = {}
    for line in lines[1:]:
        if ":" in line:
            k, _, v = line.partition(":")
            hdr[k.strip().lower()] = v.strip()
    body = await cr.readexactly(int(hdr.get("content-length", 0)))
    if target.split("?")[0] == "/health":
        return await respond(cw, 200, stats)
    if method != "POST" or target.split("?")[0] != "/v1/responses":
        return await respond(cw, 404, {"error": {"message": "this gateway serves POST /v1/responses only"}})
    try:
        req = json.loads(body) if not hdr.get("content-encoding") else {"model": MODEL}
    except ValueError:
        return await respond(cw, 400, {"error": {"message": "the body is not JSON"}})
    if req.get("model") != MODEL:
        return await respond(cw, 403, {"error": {"message": f"only the model {MODEL} is served here"}})
    body = drop_empty_assistant(req, body)
    if UP_MODEL or UP_EFFORT:
        if hdr.get("content-encoding"):
            return await respond(cw, 400, {"error": {"message": "this gateway cannot rewrite a compressed body"}})
        req = json.loads(body)
        req["model"] = UP_MODEL or MODEL
        if UP_EFFORT:
            req["reasoning"] = {**(req.get("reasoning") or {}), "effort": UP_EFFORT}
        body = json.dumps(req).encode()
    head_lines = [f"{k}: {v}" for k, v in hdr.items() if k in FORWARD]
    thread = hdr.get("thread-id") or hdr.get("session-id")
    kind = "side" if hdr.get("x-gevo-kind") in ("side", "helper") else "main"
    # The client sends nothing more after its request, so this read ends only when it goes away: it then gives up its
    # place in the queue, or its slot, at once, even if the upstream is silent.
    gone = asyncio.create_task(cr.read(1))
    logged = {}
    job = asyncio.create_task(forward(cw, slots, kind, head_lines, body, thread, logged))
    await asyncio.wait({gone, job}, return_when=asyncio.FIRST_COMPLETED)
    if job.done():
        gone.cancel()
        return job.result()
    job.cancel()
    await asyncio.wait({job})
    if not logged:
        record(thread=thread, status="client_gone")


async def forward(cw, slots, kind, head_lines, body, thread, logged):
    """Queue for a slot and send the request upstream, retrying upstream failures outside the slot."""
    waited, tries, usage = 0.0, 0, {}
    while True:
        tries += 1
        stats["queued"] += 1
        t_q = time.time()
        try:
            await slots.acquire(kind)
        finally:
            stats["queued"] -= 1
        waited += time.time() - t_q
        stats["in_flight"] += 1
        stats["peak_in_flight"] = max(stats["peak_in_flight"], stats["in_flight"])
        stats["side_in_flight"] = slots.busy["side"]
        uw = None
        try:
            t_s = time.time()
            try:
                ur, uw, status, uh = await upstream(head_lines, body)
            except (OSError, asyncio.TimeoutError, ssl.SSLError, IndexError, ValueError) as e:
                status, uh, ur = 502, {"x-gateway-error": type(e).__name__}, None
            if status in RETRY_STATUS and tries < MAX_TRIES:
                after = uh.get("retry-after", "")
                delay = min(120.0, float(after) if after.replace(".", "", 1).isdigit() else 2.0 ** tries)
                record(thread=thread, status=status, retry_in=delay, tries=tries, error=uh.get("x-gateway-error"))
            else:
                if ur is None:
                    await respond(cw, 502, {"error": {"message": "upstream connection failed"}})
                    record(thread=thread, status=502, wait=round(waited, 2), tries=tries)
                    return
                ctype = uh.get("content-type", "text/event-stream")
                cw.write(f"HTTP/1.1 {status} OK\r\nContent-Type: {ctype}\r\nCache-Control: no-store\r\n"
                         "Connection: close\r\n\r\n".encode())
                await cw.drain()
                t_first, buf, finished = None, b"", False
                try:
                    async for chunk in read_body(ur, uh):
                        if t_first is None:
                            t_first = time.time()
                        buf = scan_sse(buf + chunk, usage)
                        cw.write(chunk)
                        await cw.drain()
                    finished = True
                finally:    # a client may close as soon as it has the final event, before the upstream stream ends
                    now = time.time()
                    logged["done"] = True
                    record(thread=thread, kind=kind, status=status if finished or usage else "aborted", wait=round(waited, 2),
                           tries=tries, bytes_in=len(body), first_byte=round((t_first or now) - t_s, 2),
                           total=round(now - t_s, 2), **usage)
                    stats["served"] += 1 if finished or usage else 0
                return
        finally:
            stats["in_flight"] -= 1
            slots.release(kind)
            stats["side_in_flight"] = slots.busy["side"]
            if uw is not None:
                uw.close()
        await asyncio.sleep(delay)


async def handle(cr, cw, slots):
    try:
        await serve_one(cr, cw, slots)
    except (ConnectionError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError) as e:
        record(status="aborted", error=type(e).__name__)
    except Exception as e:      # a bad request must never take the gateway down
        record(status="gateway_error", error=repr(e)[:300])
    finally:
        try:
            cw.close()
        except Exception:
            pass


async def live():
    while True:
        tmp = os.path.join(LOGD, ".live.tmp")
        with open(tmp, "w") as o:
            json.dump(dict(stats, t=time.time()), o)
        os.replace(tmp, os.path.join(LOGD, "live.json"))
        await asyncio.sleep(5)


async def main():
    os.makedirs(LOGD, exist_ok=True)
    slots = Slots(MAXF, RESERVE)
    server = await asyncio.start_server(lambda r, w: handle(r, w, slots), os.environ.get("GATEWAY_HOST", "0.0.0.0"), PORT,
                                        limit=1 << 22)
    record(event="start", model=MODEL, upstream=BASE, max_in_flight=MAXF, main_reserved=RESERVE,
           upstream_model=UP_MODEL, upstream_effort=UP_EFFORT)
    asyncio.create_task(live())
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
