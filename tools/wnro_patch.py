#!/usr/bin/env python3
"""
NetClock 9189 GPS Week-Number-Rollover (WNRO) firmware patcher.

The Motorola Oncore M12+ receiver reports a date 1024 GPS weeks (~19.6 years) in the
past (e.g. 2007 instead of 2026): its firmware epoch ended 2019-04-07 and the board
passes the receiver's date through. This patches the board application D9189V104
(rev 1.0.4) so the GPS-derived clock is corrected by +1024 weeks (619,315,200 s).

Two small in-place changes, both in the @@Ha -> system-clock path (FUN_c000b69c):
  * 0x0BCF0 (20 bytes): add 0x24EA0000 (1024 weeks) to the 64-bit UTC seconds
    (two ADDs + register setup), replacing a dead store/reload.
  * 0x0BC44 (4 bytes):  NOP the one-shot gate (bne -> mov r0,r0) so the CORRECTED
    clock-set runs every second in steady state, not just on the first fix.
    Without this, a second code path re-disciplines the clock to the raw 2007 date.

Run it on YOUR OWN firmware dump (FTP: RETR /sys/bin/D9189V104.bin). It validates the
image and refuses anything that is not the exact D9189V104 rev 1.0.4. No Spectracom code
is included here. Valid until the receiver's next rollover (~2038).

Usage:  python3 wnro_patch.py  D9189V104.bin  D9189V104_wnro.bin   [--force]
"""
import sys, hashlib

SIZE        = 832304
ORIG_SHA    = "2f5169dc6a2f76927941cd3ae8c16a1566a81278f14528ab9e71c1a25433c99e"
PATCHED_SHA = "897993f4660cb17c8371edba1b227376930c758987cbdd3e5354ac9e9f44312b"

# (offset, expected_original, replacement)
PATCHES = [
    (0x0BCF0,
     bytes.fromhex("c0204be2180082e8020030a0e1" "030093e80520a0e1"),  # see note below
     bytes.fromhex("243483e2ea3883e20300a0e10410a0e10520a0e1")),
    (0x0BC44,
     bytes.fromhex("4f00001a"),                                       # bne 0xc000bd88
     bytes.fromhex("0000a0e1")),                                      # mov r0,r0 (NOP)
]
# NOTE: the 0x0BCF0 original is actually:
#   c0 20 4b e2 18 00 82 e8 02 30 a0 e1 03 00 93 e8 05 20 a0 e1
EXPECT_BCF0 = bytes.fromhex("c0204be2180082e80230a0e1030093e80520a0e1")

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
        print(f"ERROR: size {len(data)} != {SIZE} (D9189V104 rev 1.0.4). Aborting."); return 1
    if sha == PATCHED_SHA:
        print("Already fully patched. Nothing to do."); return 0

    sites = [
        (0x0BCF0, EXPECT_BCF0,                    bytes.fromhex("243483e2ea3883e20300a0e10410a0e10520a0e1")),  # +1024 weeks
        (0x0BC44, bytes.fromhex("4f00001a"),      bytes.fromhex("0000a0e1")),  # NOP one-shot gate (bne)
        (0x0BCE8, bytes.fromhex("023053e0"),      bytes.fromhex("0000a0e1")),  # NOP leap subs
        (0x0BCEC, bytes.fromhex("c24fc4e0"),      bytes.fromhex("0000a0e1")),  # NOP leap sbc
    ]
    for off, old, new in sites:
        cur = bytes(data[off:off+len(new)])
        if cur == new:
            print(f"  0x{off:05X}: already patched, skipping")
            continue
        if cur != old:
            print(f"  0x{off:05X}: expected {old.hex()} but found {cur.hex()}.")
            if not force:
                print("  Not the known D9189V104 patch site. Aborting (use --force to override)."); return 1
        data[off:off+len(new)] = new
        print(f"  0x{off:05X}: patched ({len(new)} bytes)")

    open(dst, "wb").write(data)
    out_sha = hashlib.sha256(bytes(data)).hexdigest()
    print(f"output: {dst}  ({len(data)} bytes, sha256 {out_sha})")
    print("OK: matches known-good patched image." if out_sha == PATCHED_SHA
          else "Patched (sites replaced); sha differs only if your input differed elsewhere.")
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv))
