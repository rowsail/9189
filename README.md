# Spectracom NetClock 9189 — JTAG recovery & web-access tools

Tools and documentation for servicing a **Spectracom NetClock 9189** time server built on
the **Triscend TA7S20 (A7S CSoC, ARM7TDMI)**: recovering a lost password over JTAG, reading
its "Delta LFS" flash filesystem, and driving its ancient GoAhead web UI from a modern
browser.

---

## ⚠️ Authorized use only — read this first

**This material is provided solely for working on hardware that YOU OWN, or that you have
explicit, documented authorization from the owner to access and service.**

The procedures here recover administrator credentials and read the full configuration out
of a device via physical JTAG access. That is a legitimate and necessary thing to do for a
unit you own whose password has been lost — and it is **not** acceptable to do to a device
you do not own or are not authorized to touch.

By using anything in this repository you agree that:

- You will use it **only** on equipment you own or are **legally authorized** to access and
  modify.
- You are responsible for complying with all applicable laws, contracts, and policies
  (including computer-misuse/anti-hacking laws and any terms you are bound by). Unauthorized
  access to computer systems is illegal in most jurisdictions.
- Recovered passwords, keys, and configuration are **sensitive**; you will handle and store
  them accordingly and will not disclose them.

The authors provide this for lawful recovery, repair, and interoperability only, with **no
warranty**. If you are not the owner of the device and do not have permission, **stop here.**

---

## What's in here

| Path | What it is |
|------|------------|
| `docs/NetClock_9189_password_recovery_via_JTAG.md` | The full write-up: JTAG bring-up (incl. the mandatory **pin-6 ground**), flash dump, Delta LFS format and file inventory, and how to change settings over serial/telnet/web. |
| `openocd/triscend_a7s.cfg` | Ready-to-use OpenOCD config for the Triscend A7S (ARM7TDMI) over a SEGGER J-Link. |
| `tools/lfs_extract.py` | Extracts files from a Delta LFS flash image (stdlib only). |
| `tools/netclock_proxy.py` | Local reverse proxy that makes the 2003-era GoAhead web UI usable in a modern browser. |
| `examples/config/` | **Sanitized** sample config files showing the on-flash format, using the firmware's **factory-default** passwords (not any real unit's) and documentation-range IPs. |

## What is deliberately **not** in here

- **Flash dumps and extracted filesystems (`dumps/`).** These contain the device's live,
  plaintext credentials (admin/config passwords, NTP keys, SNMP community strings) and logs.
  They are git-ignored on purpose — keep them on the machine that made them. For the format,
  see the sanitized `examples/config/` instead.
- **Third-party datasheets (`docs/*.pdf`).** The Triscend A7S datasheet and GoAhead debug
  notes are copyrighted by their owners and are not redistributed here.

---

## Quick start

### 1. Recover a lost password (JTAG)

See `docs/NetClock_9189_password_recovery_via_JTAG.md` for the full procedure. In short:
wire a J-Link to the JTAG header, **ground header pin 6** (buffer output-enable — the single
most common reason the chain looks dead), then:

```sh
openocd -f openocd/triscend_a7s.cfg      # confirm IDCODE 0x1843d2ff
# in the OpenOCD telnet console (:4444):
#   halt
#   dump_image dumps/triscend_flash_8MB_0xD0000000.bin 0xD0000000 0x800000
#   resume
python3 -I tools/lfs_extract.py          # -> dumps/lfs/ ; read sys/config/sec.0.cfg
```

> Leave J-Link **pin 1 (VTref) disconnected** unless you have confirmed it is safe on your
> probe (see the report, §3), and keep the probe off the board for normal cold boots.

### 2. Use the web UI from a modern browser

```sh
python3 tools/netclock_proxy.py [device_ip] [port]   # defaults 10.1.10.20 8088
# then browse http://localhost:8088/   (finish with "Exit", not "Logout")
```

The proxy handles the device's single-connection limit, its `<meta>`-delivered session
cookie, its HTTP/0.9 welcome page, and its quirky session flow. Some settings (e.g. the GPS
antenna cable delay) are web-only.

---

*No warranty. Use lawfully, on your own equipment.*
