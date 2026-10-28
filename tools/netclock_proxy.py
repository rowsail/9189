#!/usr/bin/env python3
"""
netclock_proxy.py - local reverse proxy for a Spectracom NetClock (Delta LFS /
GoAhead-Webs, ~2003 firmware) so a modern browser can use its web UI.

The device's web server has habits modern browsers can't cope with:
  1. Only ONE connection/session at a time, and NO idle timeout. Modern browsers
     open several sockets at once (page, favicon, speculative preconnects), so the
     device sees a "second user" (always yourself) and shows its lock page; and a
     session, once started, lives until goforms/exit or a cold boot.
  2. It delivers its session cookie inside the HTML as
     <meta http-equiv="Set-Cookie" content="SPEC=nn">. Firefox/Chrome dropped
     support for that years ago, so the browser never stores the cookie and
     every request looks like a brand-new session.
  3. Some pages are emitted as raw HTML with a loose header block that strict HTTP
     clients reject -- but curl tolerates it.

Device session flow (established empirically 2026-10-28):
  GET /                     -> 302 Location: /goforms/index
  GET /goforms/index        -> (no active session) the splash/frameset page that
                               MINTS a session and carries SPEC=nn in its body;
                               (active session, wrong/no cookie) the lock page
                               "only one connection ... person whose IP is X".
  POST /goforms/main        -> the real frameset, requires the SPEC cookie.
  GET  /goforms/exit        -> frees the single slot (ignores the cookie value).
  The "cookies are used for each setup session" page is the nag you get for a
  form request made without a session.

This proxy funnels every browser request through a single mutex (one upstream
request at a time), captures SPEC from whatever page body carries it, attaches it
to every request, drops favicon noise, and uses curl upstream. When the device
answers with its lock / nag page (our cookie is stale or a slot was stranded) it
frees the slot via exit, mints a fresh session with ONE cookieless GET
/goforms/index, and retries once. It never bursts: at most three upstream
requests per browser request, so it cannot wedge the fragile form engine.

Usage:
    python3 netclock_proxy.py [device_ip] [listen_port]   # defaults 10.1.10.20 8088
Then point a browser at  http://localhost:8088/
To finish cleanly, click "Exit Connection to the Product" (not Logout).
"""

import sys, re, os, threading, subprocess, tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEVICE = sys.argv[1] if len(sys.argv) > 1 else "10.1.10.20"
PORT   = int(sys.argv[2]) if len(sys.argv) > 2 else 8088
BASE   = "http://%s" % DEVICE

_lock   = threading.Lock()                             # one upstream request at a time
_cookie = {"val": os.environ.get("NETCLOCK_COOKIE")}   # device SPEC session cookie

_SKIP = {"connection", "keep-alive", "transfer-encoding", "content-length",
         "proxy-authenticate", "proxy-authorization", "te", "trailers",
         "upgrade", "content-encoding"}

# The device delivers its session as SPEC=nn (inside a <meta http-equiv=
# "Set-Cookie"> tag whose exact quoting varies). Just pull the SPEC token out of
# the page body; it appears on the session-start page, not on ordinary pages.
_SPEC = re.compile(rb"SPEC=\d+")

# Pages that mean "your request had no valid session": the lock page and the
# "go to the main page to start a valid session" nag. We must key on wording
# UNIQUE to those pages: the welcome/mint page ALSO contains the phrase
# "only one connection at a time is allowed", so that phrase must NOT be a marker
# or we would treat a freshly minted session as a failure. NOT "is not defined"
# either -- that means the web forms never registered (bad boot), unfixable by retry.
_NEEDS_SESSION = (b"try again later",                         # lock page
                  b"ask him/her to exit",                     # lock page
                  b"start a valid session",                   # nag page
                  b"cookies are used for each setup session") # nag page


def _fetch(method, path, body, ctype, use_cookie=True):
    """One upstream request via curl -> (status, headers_list, raw_body).
    curl is used because the device's HTTP/1.0 responses are too loose for
    Python's strict parser; use_cookie=False omits the session cookie."""
    upstream = "GET" if method == "HEAD" else method
    hdr = tempfile.NamedTemporaryFile(delete=False); hdr.close()
    out = tempfile.NamedTemporaryFile(delete=False); out.close()
    bf = None
    # --http0.9: the device serves its welcome/mint page (GET /goforms/index) as a
    # bare HTTP/0.9 response (raw body, no status line); modern curl rejects that by
    # default and returns nothing, so the flag is required to read it and capture SPEC.
    cmd = ["curl", "-s", "--http0.9", "-m", "25", "-D", hdr.name, "-o", out.name,
           "-w", "%{http_code}", "-X", upstream, "-A", "netclock-proxy"]
    if ctype:
        cmd += ["-H", "Content-Type: " + ctype]
    if use_cookie and _cookie["val"]:
        cmd += ["-H", "Cookie: " + _cookie["val"]]
    if body is not None:
        bf = tempfile.NamedTemporaryFile(delete=False)
        bf.write(body); bf.close()
        cmd += ["--data-binary", "@" + bf.name]
    cmd += [BASE + path]
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=30)
        code = int((p.stdout.strip() or b"0").decode() or "0")
        with open(hdr.name, "rb") as f:
            raw_hdr = f.read()
        with open(out.name, "rb") as f:
            data = f.read()
        if code == 0:
            # curl reports code 0 for an HTTP/0.9 reply (the device's welcome/mint
            # page): raw body, no status line or headers. If we actually got a body,
            # that's a real 200 response -- synthesize one. Only a truly empty reply
            # is a failure.
            if data:
                return 200, [("Content-Type", "text/html")], data
            return 502, [("Content-Type", "text/plain")], \
                   ("proxy: no response from NetClock at %s\n" % DEVICE).encode()
        return code, _parse_headers(raw_hdr), data
    except Exception as e:
        return 502, [("Content-Type", "text/plain")], \
               ("proxy error talking to %s: %s\n" % (DEVICE, e)).encode()
    finally:
        for name in (hdr.name, out.name) + ((bf.name,) if bf else ()):
            try: os.unlink(name)
            except OSError: pass


def _parse_headers(raw):
    out, text = [], raw.decode("latin1", "replace").replace("\r\n", "\n")
    for ln in text.split("\n")[1:]:              # skip the status line
        if ln.strip() and ":" in ln:
            k, v = ln.split(":", 1)
            out.append((k.strip(), v.strip()))
    return out


def _capture_cookie(body):
    m = _SPEC.search(body or b"")
    if m:
        _cookie["val"] = m.group(0).decode("latin1")


def _is_html(headers):
    for k, v in headers:
        if k.lower() == "content-type":
            vl = v.lower()
            return "html" in vl or "text" in vl
    return True                                  # device often omits content-type


def _needs_session(data):
    low = (data or b"").lower()
    return any(s in low for s in _NEEDS_SESSION)


def _mint():
    """Free any active slot, then start a fresh session. Two quirks drive this:
      * GET /goforms/index mints a session (and returns the HTTP/0.9 welcome page
        carrying SPEC=nn) ONLY when no session is active; if one is active it
        returns the lock page instead. So we must free the slot first.
      * goforms/exit frees this IP's active session only when the request carries
        *a* cookie (any value); a cookieless exit just returns the nag. So we send
        the held cookie, or a dummy, to make the exit actually take effect.
    Returns (ok, welcome_body). Caller holds _lock."""
    _cookie["val"] = _cookie["val"] or "SPEC=0"          # ensure exit carries a cookie
    _fetch("GET", "/goforms/exit", None, None, use_cookie=True)
    _cookie["val"] = None
    _, _, data = _fetch("GET", "/goforms/index", None, None, use_cookie=False)
    _capture_cookie(data)                                # welcome page carries SPEC=nn
    return bool(_cookie["val"]), data


def _drive(method, path, body, ctype):
    """One logical request against the device, (re)establishing a session only if
    the device explicitly asks for one. At most three upstream requests; never a
    burst. Caller holds _lock. Returns (status, headers, data)."""
    status, headers, data = _fetch(method, path, body, ctype)
    if _is_html(headers):
        _capture_cookie(data)                    # device may mint on this response
        if _needs_session(data):
            # Our cookie is stale or a slot was stranded: free it and mint fresh,
            # then retry the original request once with the new session cookie.
            ok, mintbody = _mint()
            if ok:
                status, headers, data = _fetch(method, path, body, ctype)
                _capture_cookie(data)
            else:
                # Could not mint (likely a bad boot: forms not registered). Serve
                # what the mint attempt returned so the symptom is visible.
                data = mintbody or data
    return status, headers, data


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s -> %s\n" % (self.command, self.path,
                         args[1] if len(args) > 1 else ""))

    def _control(self, text):
        body = text.encode()
        self.send_response(200); self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)

    def _relay(self):
        if self.path == "/__status":
            self._control("cookie=%s\n" % _cookie["val"]); return
        if self.path.startswith("/__prime/"):
            _cookie["val"] = self.path[len("/__prime/"):] or None
            self._control("cookie set to %s\n" % _cookie["val"]); return
        if self.path == "/favicon.ico":          # device has none; don't forward
            self.send_response(204); self.send_header("Content-Length", "0")
            self.end_headers(); return

        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        ctype = self.headers.get("Content-Type")

        # Entry remap: the browser reaches the UI via  / -> 302 -> GET /goforms/index.
        # But /goforms/index is the session-START page: it mints a session only when
        # NONE is active, and returns the LOCK page (even to the holder) once one is.
        # So we must NOT forward a bare GET /goforms/index while a session exists --
        # we enter the frameset via POST /goforms/main instead. _drive() mints a
        # session first if we don't hold one (exit -> cookieless GET index -> retry).
        if self.path in ("/", "/goforms/index"):
            method, path = "POST", "/goforms/main"
            body, ctype = b"B1=Enter main page", "application/x-www-form-urlencoded"
        else:
            method, path = self.command, self.path

        with _lock:
            status, headers, data = _drive(method, path, body, ctype)
            # "Exit Connection to the Product" (goforms/exit) frees the device's
            # single slot (Logout only drops to read-only). After it, forget our
            # cookie so the next visit starts a clean session.
            if "goforms/exit" in self.path.lower():
                _cookie["val"] = None

        if data and _is_html(headers):            # keep links pointed at the proxy
            data = data.replace(BASE.encode(), b"")

        self.send_response(status)
        sent_ct = False
        for k, v in headers:
            lk = k.lower()
            if lk in _SKIP:
                continue
            if lk == "location":
                v = v.replace(BASE, "")
            if lk == "content-type":
                sent_ct = True
            self.send_header(k, v)
        if not sent_ct:
            self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(data) if data else 0))
        self.end_headers()
        if data and self.command != "HEAD":
            self.wfile.write(data)

    do_GET = do_POST = do_HEAD = _relay


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    sys.stderr.write(
        "NetClock proxy: browse http://localhost:%d/  ->  device %s\n"
        "Session managed here; auto-recovers from the lock page. Ctrl-C to stop.\n"
        % (PORT, DEVICE))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
