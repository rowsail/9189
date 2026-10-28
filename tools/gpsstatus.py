#!/usr/bin/env python3
"""Fetch and pretty-print the Spectracom NetClock 9189 GPS Signal Status page.

Reads /goforms/gpsstatus through the local reverse proxy (tools/netclock_proxy.py),
which handles the device's HTTP/0.9 quirk and the single-session cookie. This is a
read-only GET: no login required, safe to poll.

Usage:
    python3 gpsstatus.py [proxy_base] [-w [interval_seconds]]

    proxy_base   base URL of the running proxy   (default http://127.0.0.1:8088)
    -w / --watch poll continuously (default every 5 s); optional number after it
                 sets the interval, e.g.  -w 2

Examples:
    python3 gpsstatus.py                 # one snapshot
    python3 gpsstatus.py -w               # watch, 5 s
    python3 gpsstatus.py -w 2             # watch, 2 s
    python3 gpsstatus.py http://10.0.0.5:8088 -w

Requires the proxy to be running:
    python3 netclock_proxy.py <device_ip> 8088
"""
import sys
import re
import time
import urllib.request

DEFAULT_BASE = "http://127.0.0.1:8088"
TIMEOUT = 12

# Antenna-sense codes -> readable
ANT = {"OK": "OK (connected)", "OC": "OPEN circuit", "UC": "SHORT circuit",
       "NV": "not valid", "Unknown": "unknown"}


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "gpsstatus.py"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read().decode("latin1", "replace")


def fetch(base):
    """Fetch gpsstatus; if the setup session timed out, re-enter once."""
    html = _get(base + "/goforms/gpsstatus")
    if "time limit has been placed" in html or "Form" in html and "not defined" in html:
        try:
            _get(base + "/")          # re-mint + enter frameset
        except Exception:
            pass
        html = _get(base + "/goforms/gpsstatus")
    return html


def parse(html):
    text = re.sub(r"<[^>]*>", " ", html)
    text = text.replace("&nbsp;", " ")
    text = re.sub(r"\s+", " ", text).strip()

    def grab(pat, default="?"):
        m = re.search(pat, text)
        return m.group(1).strip() if m else default

    info = {
        "tracking": grab(r"Tracking\s+(\d+)\s+Satellites"),
        "status":   grab(r"GPS Status\s*=\s*([^=]*?)\s+DOP"),
        "dop":      grab(r"DOP\s*=\s*([0-9.]+)"),
        "antenna":  grab(r"Antenna Sense\s*=\s*([A-Za-z]+)"),
        "lat":      grab(r"Latitude\s*=\s*([\-0-9. ]+?)\s+Longitude"),
        "lon":      grab(r"Longitude\s*=\s*([\-0-9. ]+?)\s+Quality"),
        "quality":  grab(r"Quality\s*=\s*([A-Za-z0-9]+)"),
    }

    # channel table: after "STATUS", 12 rows of 5 ints (ch, vid, mode, strength, status)
    chans = []
    m = re.search(r"CHANNEL\s+VID\s+MODE\s+STRENGTH\s+STATUS\s+(.*)$", text)
    if m:
        # 4 decimal columns (CH,VID,MODE,STRENGTH) + 1 hex column (STATUS, printed %%X)
        toks = re.findall(r"[0-9A-Fa-f]+", m.group(1))
        for i in range(0, min(len(toks), 60), 5):
            r = toks[i:i + 5]
            if len(r) == 5:
                chans.append([int(r[0]), int(r[1]), int(r[2]),
                              int(r[3]), int(r[4], 16)])
    return info, chans


def render(info, chans):
    out = []
    ant = ANT.get(info["antenna"], info["antenna"])
    tracked = sum(1 for c in chans if c[3] > 0)   # strength > 0
    out.append("  GPS Signal Status")
    out.append("  " + "-" * 44)
    out.append(f"  Status      : {info['status']}")
    out.append(f"  Tracking    : {info['tracking']} satellites "
               f"({tracked} with signal)")
    out.append(f"  Fix quality : {info['quality']}        DOP: {info['dop']}")
    out.append(f"  Antenna     : {ant}")
    out.append(f"  Position    : lat {info['lat']}   lon {info['lon']}")
    if chans:
        out.append("")
        out.append("  CH  VID  MODE  STRENGTH             STATUS")
        for ch, vid, mode, stg, st in chans:
            bar = "#" * min(stg, 20)
            mark = "  <-- signal" if stg > 0 else ""
            out.append(f"  {ch:>2}  {vid:>3}  {mode:>4}  {stg:>3} {bar:<20} 0x{st:04X}{mark}")
    return "\n".join(out)


def main(argv):
    base = DEFAULT_BASE
    watch = False
    interval = 5.0
    args = argv[1:]
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-w", "--watch"):
            watch = True
            if i + 1 < len(args) and re.fullmatch(r"[0-9.]+", args[i + 1]):
                interval = float(args[i + 1]); i += 1
        elif a in ("-h", "--help"):
            print(__doc__); return 0
        elif a.startswith("http"):
            base = a.rstrip("/")
        else:
            sys.stderr.write(f"ignoring unknown argument: {a}\n")
        i += 1

    def once():
        try:
            info, chans = parse(fetch(base))
            return render(info, chans)
        except Exception as e:
            return f"  error talking to proxy at {base}: {e}\n" \
                   f"  (is netclock_proxy.py running?)"

    if not watch:
        print(once())
        return 0
    try:
        while True:
            sys.stdout.write("\x1b[2J\x1b[H")   # clear screen
            print(once())
            print(f"\n  (watching every {interval:g}s — Ctrl-C to stop)")
            time.sleep(interval)
    except KeyboardInterrupt:
        print()
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
