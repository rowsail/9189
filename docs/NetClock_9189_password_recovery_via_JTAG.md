# Recovering a Spectracom NetClock 9189 with an Unknown Password (via JTAG)

**Applies to:** Spectracom NetClock 9189 built on the Triscend **TA7S20-33QC** (A7S
CSoC, ARM7TDMI core, 208-pin PQFP), firmware circa 2002–2003 using the "Delta LFS"
log-structured filesystem.

**Use this when:** you own a unit but have lost the admin (and/or config) password and
cannot log in over the web, telnet, or serial console. There is no documented factory
password reset. Because the credentials are stored *in the clear* inside the device's
flash filesystem, the reliable recovery path is to read the flash over JTAG and extract
the password from the configuration file. No writing to the device is required — this is
a read-only recovery.

> **Authorization:** this procedure requires physical possession of the unit and is
> intended for recovering a device you own or are authorized to service. It reads
> secrets out of the hardware; treat the recovered password as sensitive.

---

## 1. Summary of the recovery path

1. Connect a JTAG debug probe to the board's JTAG header (standard ARM-style header).
2. **Ground header pin 6** — it is the output-enable for the buffers between the header
   and the processor. Without it the JTAG chain is dead (see §3; this is the single most
   common reason a recovery "doesn't work").
3. Bring up OpenOCD and confirm the ARM7TDMI is on the scan chain (IDCODE `0x1843d2ff`).
4. Dump the 8 MB external flash to a file.
5. Extract the Delta LFS filesystem from the dump.
6. Read `sys/config/sec.0.cfg` — it contains `admin_pass` and `config_pass` in plain text.

Expect the whole process to take well under an hour once the probe is wired correctly.

---

## 2. What you need

**Hardware**
- A SEGGER J-Link (or compatible ARM JTAG probe). A **J-Link V8 clone** works fine; see
  the clone caveat in §3.
- Jumper leads to the board's JTAG header. A proper ribbon/IDC connector is strongly
  preferred over individual flying leads — see the pin-6 warning in §3.
- The host PC running OpenOCD.

**Software**
- OpenOCD 0.12.0 or newer (the generic `arm7tdmi` target is sufficient).
- Python 3 (standard library only) for the filesystem extractor.
- Repo files referenced below:
  - `openocd/triscend_a7s.cfg` — ready-to-use OpenOCD config.
  - `tools/lfs_extract.py` — Delta LFS extractor.
  - `docs/Triscend_A7S_datasheet_TCH305-0001-002.pdf` — the A7S datasheet.

---

## 3. JTAG connection — and the pin-6 ground (read this twice)

The board exposes a **standard ARM JTAG header**. Electrically you only need five
signals to read flash:

| Signal | Notes |
|--------|-------|
| TCK    | clock |
| TMS    | mode select |
| TDI    | data in |
| TDO    | data out |
| GND    | common ground — **and see pin 6 below** |

nRESET / nTRST are **not** required; the OpenOCD config uses `reset_config none`.

### ⚠️ Pin 6 of the header MUST be tied to ground

The Triscend's four JTAG pins do not come straight out to the header. They pass through
**74LVC125 buffers**, and the **output-enable of those buffers is wired to header pin 6**.
The buffers are enabled only when **pin 6 is pulled low (grounded)**. If pin 6 floats,
the buffers stay in high-impedance, nothing reaches the processor's TDO, and the probe
sees a dead chain — **no IDCODE, no TAP, "all ones" or "all zeros" on the scan.** It looks
exactly like a broken probe or wrong wiring, but the fix is simply grounding pin 6.

**Why this bites people using single wires:** when you wire the header with individual
flying leads (DuPont jumpers) instead of a proper ribbon cable, it is very easy to land
TCK/TMS/TDI/TDO/GND and *forget pin 6 entirely*, or to leave a flaky single-strand lead
on pin 6 that doesn't actually seat. The JTAG signals are all present and correct, yet the
chain is still dead because the buffers were never enabled. **Always run a dedicated,
known-good ground wire to pin 6** (in addition to the normal GND), and confirm it with a
meter before blaming anything else. With a proper ribbon connector this "just works"
because pin 6 is carried along with everything else; with loose single wires it is the
first thing to check.

### ⚠️ J-Link **clone** caveat — leave pin 1 disconnected

**As a precaution, do not connect probe pin 1 (VTref) until you have confirmed it is safe
on your specific probe.** On a genuine J-Link, pin 1 is a VTref *sense input*. On the V8
clones commonly in use here there is reason to suspect pin 1 may instead be *driven* (so
connecting it could back-power the target, fight the board's rails, and make VTref/VTarget
readings meaningless) — but this has **not been positively confirmed**, so treat it as
unverified. OpenOCD does not need a valid VTref reading to drive this target, so there is no
downside to leaving pin 1 off. If you want to use it, measure pin 1 against ground with the
probe powered and the board disconnected first, and only connect it if it reads as a
high-impedance input rather than a driven rail.

### ⚠️ Keep the probe OFF the board for normal operation

Separately from recovery: leaving the probe connected (pin 6 grounded) across a **cold
boot** interferes with the Triscend's power-on configuration load and can leave the web/
application subsystem half-initialized. **Disconnect the probe after you finish dumping,
then cold power-cycle** for normal use. The probe is only needed for the flash dump.

---

## 4. Bring up OpenOCD and verify the chain

Use the supplied config:

```sh
openocd -f openocd/triscend_a7s.cfg
```

Key contents (already set in `openocd/triscend_a7s.cfg`):

```
adapter driver jlink
transport select jtag
adapter speed 1000
reset_config none
jtag newtap a7 cpu -irlen 4 -ircapture 0x1 -irmask 0xf -expected-id 0x1843d2ff
target create a7.cpu arm7tdmi -endian little -chain-position a7.cpu
```

In another terminal, connect to the OpenOCD telnet console and confirm the TAP:

```sh
telnet localhost 4444
> scan_chain
```

You should see the TAP with **IDCODE `0x1843d2ff`** (IR length 4, IR capture `0x1`). This
IDCODE is stable from 100 kHz up to ~4 MHz TCK. If you get `0x00000000`,
`0xffffffff`, or "no device found", **go back to §3 and check pin 6 first.**

A quick liveness check:

```
> halt
> arm reg
> mdw 0xD1010000 4     ;# control registers read back non-garbage
```

---

## 5. Dump the external flash

The firmware and configuration live in 8 MB of external x16 flash mapped at
**`0xD0000000`–`0xD07FFFFF`** (the device mirrors this image every 8 MB up to
`0xD0FFFFFF`; one 8 MB copy is all you need).

From the OpenOCD telnet console:

```
> halt
> dump_image dumps/triscend_flash_8MB_0xD0000000.bin 0xD0000000 0x800000
> resume
```

At 4 MHz TCK this runs around ~46 KiB/s. **Verify the dump** by reading it twice (e.g. at
1 MHz and 4 MHz) and comparing `sha256sum` — the two must match. The known-good reference
image in this repo is `dumps/triscend_flash_8MB_0xD0000000.bin`
(sha256 begins `57dd8c73…`).

The last 32 bytes of the 8 MB image are the Triscend boot header (it ends with
`0x1803d2ff`); seeing that is a good sanity check that you captured the window correctly.

> After dumping, **disconnect the probe and cold power-cycle** the unit (§3).

---

## 6. Extract the Delta LFS filesystem

The flash holds a **log-structured filesystem** ("Delta LFS"). Each file record begins on a
256-byte (`0x100`) boundary with a header that carries a Spectracom copyright tag, the
filename (at +0x60), the path (at +0x80), and the data length (at +0xBC), followed by the
file data. Because the filesystem is log-structured, the same path can appear several
times; the **last** copy is the current one.

Run the extractor (standard library only; `-I` isolates it from the untrusted dump dir):

```sh
python3 -I tools/lfs_extract.py
```

It writes the newest version of each file into `dumps/lfs/`, reproducing the device's
directory tree, including:

- `data/BOOTV104.bin`        — boot loader
- `sys/bin/D9189V104.bin`    — main application
- `sys/config/*.cfg`         — configuration (net, ntpd, snmp, **sec**, …), plain text
- `sys/logs/*`               — GPS and ring-buffer logs

---

## 7. Read the password

The credentials are in **`dumps/lfs/sys/config/sec.0.cfg`**, in clear text, as two keys:

```
admin_pass   <the admin password>
config_pass  <the configuration password>
```

- `admin_pass` is the account you use to log in at full privilege (the `admin` account).
- `config_pass` gates configuration changes.

Read the file however you like, e.g.:

```sh
cat dumps/lfs/sys/config/sec.0.cfg
```

If you only need it for scripted re-entry and want to avoid shoulder-surfing, load it into
a variable instead of printing it:

```sh
ADMIN_PASS=$(sed -nE 's/^admin_pass[=: \t]+(\S+).*/\1/p' dumps/lfs/sys/config/sec.0.cfg)
```

> Treat `sec.0.cfg` as a secret. It also reveals SNMP community strings and NTP keys from
> the other `*.cfg` files if those were configured.

A sanitized illustration of this file (format only, with the **factory-default** values
rather than any real credentials) is in [`examples/config/sec.0.cfg`](../examples/config/sec.0.cfg).

### 7.1 Factory-default credentials and hardcoded accounts

If the unit was never changed from defaults — or you reset it with `goforms/default` /
`restore` or the CLI `sec default` — the passwords revert to values **compiled into the
firmware**. The firmware (`D9189V104.bin`) contains this account table:

| Account | Default password | Role |
|---------|------------------|------|
| `user`   | `user1234`       | read-only |
| `config` | `config12`       | configuration access |
| `admin`  | `admin123`       | full administrator |
| `debug`  | *(withheld)*      | **hardcoded service/debug account** — value intentionally not published |

> **Security note.** `admin`/`config`/`user` are the documented factory defaults — change
> them on any unit in service. The `debug` account is a **hardcoded credential baked into
> the firmware image**, identical across all units of this (long-EOL, ~2003) firmware and
> not resettable from the UI. It is documented here as a defensive finding: if you operate
> one of these units, isolate its management interfaces (serial/telnet/web/SNMP) on a
> trusted network — the backdoor cannot be removed without new firmware.

---

## 8. Using the recovered password

Once you have `admin_pass`, you can regain control without JTAG:

- **Serial console** (RS-232, **9600 8N1**): `login admin <admin_pass>` →
  `Security Level is now: Admin Level`. Secured commands (e.g. `reboot`) then work.
- **Telnet** (port 23): same `login admin <admin_pass>` CLI.
- **Web UI**: the GoAhead-Webs server (≈2003) is hostile to modern browsers (single
  connection, cookie delivered via a `<meta http-equiv="Set-Cookie">` tag, HTTP/0.9
  welcome page). Use `tools/netclock_proxy.py` as a local reverse proxy if you need the
  web pages (some settings, such as the GPS antenna cable delay, are web-only).

If instead you simply want the unit usable again and don't care about existing config, you
can log in with the recovered password and re-provision, or (with admin rights) restore
defaults per group from the CLI.

---

## 9. Quick troubleshooting

| Symptom | Most likely cause |
|---------|-------------------|
| No IDCODE / `0x00000000` / `0xffffffff` on scan | **Pin 6 not grounded** (buffers disabled). Check this *first*, especially with single flying leads. |
| Chain intermittently drops | Flaky single-wire lead on pin 6 or TCK; reseat / use a ribbon. |
| VTref/VTarget reads wrong or board back-powered | Probe **pin 1 connected** — disconnect it (see §3; pin 1 is best left off until proven safe). |
| Dump differs between runs | Lower TCK (try 1 MHz) and re-verify by sha256. |
| Web/app subsystem flaky after recovery | Probe was attached across a cold boot — disconnect and cold power-cycle. |
| `scan_chain` fine but can't halt | Confirm `reset_config none` and that you're on the `arm7tdmi` target. |

---

## 10. Reference values (this platform)

- Processor: Triscend TA7S20-33QC, ARM7TDMI, 208-pin PQFP.
- JTAG IDCODE: `0x1843d2ff` (IR len 4, IR capture `0x1`).
- TA7S20 PQFP pin map (for probing at the chip, if ever needed):
  TDI = 6, TMS = 7, TCK = 8, TDO = 9; SLAVE- = 82, VSYS = 83, RST- = 84.
- Memory map: control regs `0xD1010000`, on-chip SRAM `0xD1030000`,
  config memory `0xD1040000`, external flash base `0xD0000000` (8 MB, mirrored every 8 MB).
- Config file with credentials: `sys/config/sec.0.cfg` (`admin_pass`, `config_pass`).

---

## 11. The Delta LFS filesystem and what each file holds

### 11.1 Why it's a log-structured filesystem (LFS)

The 8 MB flash does not hold a conventional FAT/overwrite-in-place filesystem. It uses
Spectracom's **"Delta LFS"**, a *log-structured* filesystem: when a file is written or
changed, the new version is **appended** to the log rather than overwriting the old one.
The most recently appended copy of a given path is the live one; older copies are stale
history waiting to be reclaimed. This design is deliberate for an embedded box with raw
NOR flash:

- **Power-fail safety** — an interrupted write cannot corrupt the previous good copy,
  because that copy is never erased in place. A half-written new record is simply ignored.
- **Flash wear levelling** — appends spread writes across the device instead of hammering
  one sector on every config change.

The practical consequence for recovery: **a single path can appear multiple times in the
dump**, and you must keep the *last* occurrence. The extractor (`tools/lfs_extract.py`)
does exactly this — it walks every record and emits the newest version of each path.

### 11.2 On-flash record format

Each file record begins on a 256-byte (`0x100`) boundary with a fixed header, followed by
the file's data:

| Offset | Field | Notes |
|--------|-------|-------|
| `+0x00` | Copyright tag | ASCII `"(c)Copyright 2002 Spectracom"` — the record marker |
| `+0x2B` | `"Delta LFS"` | literal substring the extractor scans for |
| `+0x60` | File name | NUL-terminated |
| `+0x80` | Path | NUL-terminated, device-relative (e.g. `sys/config`) |
| `+0xBC` | Data length | little-endian `uint32` |
| `+0x100` | File data | `length` bytes |

The extractor finds records by scanning for `"Delta LFS"`, backing up `0x2B` to the header
start, validating the copyright tag and the `0x100` alignment, then reading name/path/length.

### 11.3 What each file is

Running `python3 -I tools/lfs_extract.py` yields the tree below (sizes from this unit).
The `*.0.cfg` naming is the log generation; `.0` is the current generation.

**Firmware images**

| File | Size | Purpose |
|------|------|---------|
| `data/BOOTV104.bin`     | ~411 KB | Boot loader (starts with the ARM reset vectors) |
| `sys/bin/D9189V104.bin` | ~813 KB | Main NetClock application (the CLI, the GoAhead web server, GPS/NTP stacks) |

**Configuration** (`sys/config/`) — the live settings; these are what the CLI and web UI edit

| File | Size | Holds |
|------|------|-------|
| `sec.0.cfg`     | 2 KB  | **Security: `admin_pass`, `config_pass`** (plain text) |
| `net.0.cfg`     | 1 KB  | Network: `address`, `mask`, `gateway`, `gateflag` (gateway-enable) |
| `gps.0.cfg`     | 1.25 KB | GPS receiver settings: `leapsecondstatus`, `utcoffset`, antenna cable delay, etc. |
| `ntpd.0.cfg`    | 1.75 KB | NTP daemon configuration (peers/servers, broadcast, auth enable) |
| `ntpkeys.0.cfg` | 8 KB  | NTP authentication key table (**secret** key material) |
| `snmp.0.cfg`    | 1.75 KB | SNMP: community strings (**secret**) and trap destinations |
| `rly.0.cfg`     | 768 B | Programmable relay configuration |
| `evsch.0.cfg`   | 32 KB | Event scheduler table (timed relay/output events) |
| `ftp.0.cfg`     | 256 B | FTP server `enable` flag |
| `telnet.0.cfg`  | 256 B | Telnet server `enable` flag |
| `dp1.0.cfg`, `dp3.0.cfg` | 3.25 KB each | Front-panel / display-port profiles |

**Logs** (`sys/logs/`) — fixed-size ring buffers (each ~68 KB; `*.temp` are rotation scratch copies)

| File | Purpose |
|------|---------|
| `GPSLog.csv`    | GPS fix/track history as CSV |
| `trackhist`     | Satellite tracking history |
| `operational`   | Operational event log |
| `system`        | System log |
| `alarms`        | Alarm history |
| `evsch`         | Event-scheduler activity log |

> Secrets are **not** confined to `sec.0.cfg`: `ntpkeys.0.cfg` and `snmp.0.cfg` also carry
> credential material. Handle the whole `sys/config/` tree as sensitive.

---

## 12. Changing configuration settings (serial, telnet, web)

All three interfaces are front-ends to the **same** configuration store — the `sys/config/*.cfg`
files above. A change made over serial is visible over telnet and the web, because they all
read and write the same LFS records. Pick whichever interface is reachable.

### 12.1 Serial console

- **Port:** RS-232, **9600 8N1**, no flow control. (`screen /dev/ttyUSB0 9600`, or any
  terminal; exit `screen` with `Ctrl-a` `k` `y`.)
- You land at a `>` prompt. `help` lists the command groups.
- **Privilege:** viewing is open, but changing most settings or rebooting requires
  `login admin <admin_pass>` first (→ `Security Level is now: Admin Level`). `logout`
  drops back down.

### 12.2 Telnet

Identical CLI to the serial console, over **TCP port 23** (must be enabled in
`telnet.0.cfg`). Same `login admin <admin_pass>` requirement for changes. The telnet/serial
CLI is a **separate subsystem from the web server**, which makes it the reliable way to,
e.g., `reboot` the unit when the web UI is stuck.

### 12.3 CLI command model (serial and telnet)

Commands are grouped by subsystem, each following a consistent verb pattern:

```
<group> show              # display current settings
<group> set <field> <val> # change a setting
<group> default           # restore this group's defaults
<group> help              # list the group's commands
```

Observed groups: `net`, `gps`, `clock`, `ntpd`, `snmp`, `telnet`, `ftp`, `web`, `rly`,
`evsch`, `sec`, `sup`, `log`, `fs` — matching the `*.cfg` files in §11.3.

**Example — set the network address over the CLI:**

```
login admin <admin_pass>
net show
net ip 10.1.10.20
net mask 255.255.255.0
net gateway yes 10.1.10.1
net show
reboot                 # network changes take effect on restart
```

Writes persist by appending a new generation of the relevant `*.cfg` record (the LFS
behaviour in §11.1). Some changes (network, certain GPS options) apply only after `reboot`.

### 12.4 Web UI (GoAhead-Webs forms)

The web server is an early-2000s **GoAhead-Webs** instance. Each configuration area has a
**display page** and a matching **update handler** whose name ends in `u`; the page's HTML
form `POST`s the changed fields to the `…u` handler:

| Area | Display page | Update handler (POST target) |
|------|--------------|------------------------------|
| Network      | `goforms/netconfig`   | `goforms/netu` |
| GPS          | `goforms/gpsconfig`   | `goforms/gpsu` |
| NTP          | `goforms/ntp`         | `goforms/ntpu` |
| SNMP         | `goforms/snmp`        | `goforms/snmpu` |
| Alarms       | `goforms/alarmconfig` | `goforms/alarmu` |
| Events       | `goforms/eventconfig` | `goforms/eventu` |
| Relays       | `goforms/relayconfig` | `goforms/relayu` |
| Serial ports | `goforms/serial1`     | `goforms/serial1u`, `goforms/serial2u` |
| Remote out   | `goforms/remote1`     | `goforms/remote1u`, `goforms/remote2u` |
| Time zone / DST / UTC | `goforms/autotimezone`, `goforms/autodst`, `goforms/utctime` | `goforms/timezoneu`, `goforms/dstu`, `goforms/utcu` |
| IRIG         | (on a config page)    | `goforms/irigu` |
| Defaults     | —                     | `goforms/default`, `goforms/restore` |
| Session      | `goforms/admin_login`, `goforms/config_login` | `goforms/logout` (read-only), `goforms/exit` (free the slot) |

Authentication for edits is via the login bar (`admin_login` with `admin_pass`); some pages
read-only until you authenticate.

**Why the web UI needs a proxy:** this server is hostile to modern browsers —
- only **one connection/session at a time**, with **no idle timeout**;
- the session cookie is delivered in-page via `<meta http-equiv="Set-Cookie" content="SPEC=nn">`,
  which modern browsers ignore;
- the welcome/mint page is served as bare **HTTP/0.9**;
- `GET /goforms/index` mints a session only when none is active and otherwise returns the
  lock page; you enter the frameset with `POST /goforms/main`; and the slot is freed only by
  `goforms/exit` **with** a cookie (not `logout`, which just drops to read-only).

`tools/netclock_proxy.py` encapsulates all of this: run `python3 tools/netclock_proxy.py`
and browse `http://localhost:8088/`. Finish with **Exit** (not Logout) to release the slot.

**Web-only settings:** a few parameters have no CLI equivalent and must be set from the web
UI — notably the **GPS antenna cable delay** (`goforms/gpsconfig`, field `name='cable'`, in
nanoseconds, posted to `goforms/gpsu`). Delay is computed as `D = (L × 1.016) / V` where
`L` = cable length in feet and `V` = the coax velocity factor.

---

*Prepared from hands-on work on this unit, 2026-10. The JTAG bring-up, flash dump, LFS
extraction, CLI, and (proxied) web UI were all verified on the actual board.*
