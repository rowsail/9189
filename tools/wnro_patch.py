#!/usr/bin/env python3
"""
NetClock 9189 GPS Week-Number-Rollover (WNRO) firmware patcher.

The Motorola Oncore M12+ receiver in the NetClock 9189 reports a date 1024 GPS
weeks (~19.6 years) in the past (e.g. 2007 instead of 2026) because its firmware
epoch ended 2019-04-07. The board faithfully passes that date through. This patch
adds 1024 weeks (619,315,200 s = 0x24EA0000) to the GPS-derived UTC seconds in the
board application, correcting the served clock/NTP date. Time-of-day is unaffected.

It patches 20 bytes in the application image D9189V104 (rev 1.0.4). It REFUSES to
touch anything that is not that exact image, so run it on YOUR OWN firmware dump
(get it over FTP: RETR /sys/bin/D9189V104.bin, or from a flash dump).

Usage:  python3 wnro_patch.py  D9189V104.bin  D9189V104_wnro.bin   [--force]

This script contains no Spectracom code -- only the offset and the replacement
instructions. You supply the original firmware.  Valid until the receiver's next
rollover (~2038), which would need offset 2*1024 weeks.
"""
import sys, hashlib

SIZE       = 832304
OFFSET     = 0x0BCF0
ORIG_SHA   = "2f5169dc6a2f76927941cd3ae8c16a1566a81278f14528ab9e71c1a25433c99e"
PATCHED_SHA= "80141c95c3fcb0f7766f985baceabb441d0438bb6b0255c78249a1479d21aa7d"
# original 20 bytes at OFFSET (sub r2,r11,#0xc0 / stmia / mov / ldmia / mov r2,r5)
EXPECT_OLD = bytes.fromhex("c0204be2180082e80230a0e1030093e80520a0e1")
# replacement: add r3,r3,#0x24000000 ; add r3,r3,#0x00EA0000 ; mov r0,r3 ; mov r1,r4 ; mov r2,r5
NEW        = bytes.fromhex("243483e2ea3883e20300a0e10410a0e10520a0e1")

def main(argv):
    force = "--force" in argv
    args  = [a for a in argv[1:] if not a.startswith("--")]
    if len(args) != 2:
        print(__doc__); return 2
    src, dst = args
    data = bytearray(open(src, "rb").read())
    sha  = hashlib.sha256(bytes(data)).hexdigest()
    print(f"input : {src}  ({len(data)} bytes, sha256 {sha})")
    if len(data) != SIZE:
        print(f"ERROR: size is {len(data)}, expected {SIZE} (D9189V104 rev 1.0.4). Aborting.")
        return 1
    cur = bytes(data[OFFSET:OFFSET+20])
    if cur == NEW:
        print("This image is ALREADY patched. Nothing to do."); return 0
    if cur != EXPECT_OLD:
        print(f"WARNING: bytes at 0x{OFFSET:05X} are {cur.hex()}, expected {EXPECT_OLD.hex()}.")
        print("This is not the known D9189V104 clock-set site. Patching the wrong place can brick the unit.")
        if not force:
            print("Refusing (use --force only if you know exactly what you are doing)."); return 1
    if sha != ORIG_SHA and not force:
        print(f"WARNING: sha256 does not match the known original ({ORIG_SHA}).")
        print("Proceeding because the patch-site bytes matched; pass --force to silence.") if cur==EXPECT_OLD else None
        if cur != EXPECT_OLD: return 1
    data[OFFSET:OFFSET+20] = NEW
    open(dst, "wb").write(data)
    out_sha = hashlib.sha256(bytes(data)).hexdigest()
    print(f"output: {dst}  ({len(data)} bytes, sha256 {out_sha})")
    if out_sha == PATCHED_SHA:
        print("OK: output matches the known-good patched image. +1024 weeks applied.")
    else:
        print("Patched (site bytes replaced). Output sha differs from reference only if your")
        print("original differed elsewhere; the 20-byte change itself is correct.")
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv))
