#!/usr/bin/env python3
"""
lfs_extract.py - extract files from a Spectracom "Delta LFS" flash image.

The Spectracom NetClock 9189 (Triscend A7S) stores firmware, configuration and logs
in a log-structured filesystem. Each file record starts on a 256-byte (0x100)
boundary with a header (copyright tag at +0x00, "Delta LFS" at +0x2b, file name at
+0x60, path at +0x80, little-endian length at +0xBC) followed by the data. Because
the filesystem is log-structured, a path can appear many times; the LAST valid copy
is the live one, which is what this tool keeps.

Usage:
    python3 -I lfs_extract.py [flash_image] [output_dir]
    # defaults: ./dumps/triscend_flash_8MB_0xD0000000.bin  ->  ./dumps/lfs

Run under `python3 -I` since the input is an untrusted binary dump.
"""

import os, struct, sys

IMG = sys.argv[1] if len(sys.argv) > 1 else "dumps/triscend_flash_8MB_0xD0000000.bin"
OUT = sys.argv[2] if len(sys.argv) > 2 else "dumps/lfs"
SIG = b'(c)Copyright 2002 Spectracom'
HDR = 0x100

d = open(IMG, 'rb').read()


def cstr(b):
    z = b.find(b'\0')
    return (b if z < 0 else b[:z]).decode('latin1').strip()


# Real headers sit on 0x100 boundaries. The "Delta LFS" substring is at +0x2b.
heads = []
i = 0
while True:
    i = d.find(b'Delta LFS', i)
    if i < 0:
        break
    o = i - 0x2b
    if o >= 0 and (o & 0xff) == 0 and d[o:o+len(SIG)] == SIG:
        heads.append(o)
    i += 1

records = []
for o in heads:
    name = cstr(d[o+0x60:o+0x80])
    path = cstr(d[o+0x80:o+0xb0])
    size = struct.unpack_from('<I', d, o+0xbc)[0]
    records.append((o, path, name, size))

# log-structured: a later record for the same path/name supersedes earlier ones;
# keep the latest valid copy.
latest = {}
for o, path, name, size in records:
    if not name:                 continue
    if size in (0, 0xffffffff):  continue
    if o + HDR + size > len(d):  continue
    latest[(path, name)] = (o, size)

os.makedirs(OUT, exist_ok=True)
rows = []
total = 0
for (path, name), (o, size) in sorted(latest.items()):
    rel = (path.lstrip('/') + name)
    dst = os.path.join(OUT, rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, 'wb') as f:
        f.write(d[o+HDR:o+HDR+size])
    rows.append((path, name, size, o))
    total += size

print("header records found: %d" % len(records))
print("files extracted:      %d  (%d bytes)" % (len(rows), total))
print()
print("%-16s %-22s %10s  %-10s" % ("PATH", "NAME", "SIZE", "FLASH@"))
for path, name, size, o in rows:
    print("%-16s %-22s %10d  0x%06x" % (path, name, size, o))
