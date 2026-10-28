# NetClock 9189 — fix the GPS date rollover (WNRO) over FTP

The Motorola Oncore **M12+** receiver in the 9189 reports a date **1024 GPS weeks
(~19.6 years) in the past** — e.g. **2007 instead of 2026** — because its firmware's
GPS-week epoch ended **2019‑04‑07**. The time‑of‑day is correct; only the week/date is
wrong, and the board passes the receiver's date straight through. There is no M12+ firmware
that removes this, so the fix is a small **board‑firmware patch**: add 1024 weeks
(619,315,200 s) to the GPS‑derived time. This applies entirely **over the network via FTP** —
no JTAG, and serial only if you need to recover a bad flash.

> ⚠️ **For your own unit only.** Modifying device firmware is at your own risk. Do **not**
> redistribute the patched Spectracom binary — patch your own firmware with the script here.
> Scope: application **D9189V104 rev 1.0.4** (832,304 bytes). Different versions aren't covered.
> The +1024‑week correction is valid until the receiver's next rollover (~2038).

## What the patch does
Four small in‑place changes to `D9189V104.bin`, all in the `@@Ha` → system‑clock path
(`FUN_c000b69c`), applied by the patcher. Same size, no code cave, no calendar math:
- **0x0BCF0 (20 bytes):** add `0x24EA0000` (1024 weeks) to the 64‑bit seconds — corrects the date.
- **0x0BC44 (4 bytes):** NOP a one‑shot gate so the corrected clock‑set runs every second in
  steady state (otherwise a second path re‑disciplines the clock to the raw 2007 date).
- **0x0BCE8 + 0x0BCEC (4+4 bytes):** NOP that path's leap‑second subtraction. The time it reads
  is already UTC, so the extra subtraction left the clock 18 s slow; removing it restores
  correct time‑of‑day alongside the corrected date.

Verified on hardware: a 3D fix yields the correct date **and** time (offset <1 s vs public NTP),
with NTP reporting LI=0 (synchronized). (Full RE in the patcher source and repo notes.)

## You need
- Python 3, and `tools/wnro_patch.py` from this repo.
- Network access to the unit; its **admin** password (factory default `admin123` if never changed).
- Recommended: an **RS‑232 serial cable** to the console port on standby — the *only* way to
  recover if a flash goes bad (the FTP server is part of the app, so it won't be running then).

## Steps

**1. Back up the original firmware.** Pull your unit's current app over FTP:
```
ftp <unit-ip>          # log in as admin
binary
get /sys/bin/D9189V104.bin  D9189V104.orig.bin
quit
```
Keep `D9189V104.orig.bin` safe — it's your rollback image. (A full JTAG flash dump is even better if you have it.)

**2. Build the patched image.**
```
python3 tools/wnro_patch.py  D9189V104.orig.bin  D9189V104_wnro.bin
```
The script verifies it's the right firmware (size + patch‑site bytes) and refuses otherwise.
It prints `OK: ... +1024 weeks applied.` on success.

**3. Upload the patched image.** The LFS can't overwrite a file in place, so **delete then store**:
```
ftp <unit-ip>          # admin
binary
delete /sys/bin/D9189V104.bin
put D9189V104_wnro.bin /sys/bin/D9189V104.bin
```
The `put` takes ~40 s (flash programming) — **be patient and raise your client's timeout**;
some clients report a timeout while the write actually completes. Then verify:
```
get /sys/bin/D9189V104.bin  readback.bin
quit
# compare: sha256 readback.bin  == sha256 D9189V104_wnro.bin
```
Do **not** reboot until the readback matches your patched image.

**4. Activate it — reboot.** Either power‑cycle, or over telnet (admin):
```
telnet <unit-ip>
login admin <password>
reboot
```
It comes back in well under a minute (BOOTV104 loads the newest `/sys/bin` image).

**5. Verify.** Once the GPS has a fix, the served date is correct (query NTP, or the web GPS
status / system time). Before: a fix shows the old year; after: the real year.

## Recovery (if it won't boot)
The "press any key to escape to shell mode" BootMonitor prompt appears on **every** power‑up,
before the app loads, over the **serial console** (9600 8N1). From it (debug login) you can
erase the app sectors and re‑upload your `D9189V104.orig.bin` as S‑records. That's why a serial
cable on standby is recommended. (JTAG is an additional, optional safety net.)

## Notes
- Fixes the **date**; needs a solid multi‑satellite fix for NTP to flag itself fully
  synchronized (good antenna sky view) — unrelated to this patch.
- Re‑apply after any future full‑firmware reload.
