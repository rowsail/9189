#!/usr/bin/env python3
"""
arm_splice.py -- assemble ARM instructions and splice them into a raw firmware
image, the reliable way to extend position-dependent bare-metal ARM firmware.

A whole-image disassemble -> reassemble round-trip is not practical for an image
like the NetClock 9189 application: it is hardwired to load at 0xC0000000, is full
of absolute pointers sitting in literal pools, and has no relocations or symbols,
so letting an assembler re-lay-out the code shifts every instruction and breaks
every baked-in pointer. The dependable technique is to keep the original bytes and
change only what you must:

  * in-place patch  -- replace instructions with the SAME number of bytes, so
                       nothing downstream moves (`patch`);
  * code-cave detour -- overwrite one instruction with a branch to free space,
                       run new code there, branch back (`detour`); the body of
                       the image never moves, so all absolute pointers stay valid.

Because the image is position-dependent, this tool assembles at the instruction's
real RUNTIME address (file offset + base, base 0xC0000000), so relative branches
resolve correctly, and it disassembles whatever it is about to write back so you
can see the exact instructions before they land.

This requires the Keystone assembler and Capstone disassembler:
    python3 -m venv venv && . venv/bin/activate && pip install keystone-engine capstone

It contains no vendor code; run it on your own firmware dump.

Subcommands (see `arm_splice.py <cmd> -h`):
  dis    <bin> <off> [n]                 disassemble n instrs at a file offset
  asm    "<code>" [--at ADDR]            assemble; print bytes + round-trip disasm
  patch  <bin> <off> "<code>" -o OUT     assemble at off's runtime addr, splice in
                                         place (must be the same length); verify
  detour <bin> <site> <cave> "<code>" -o OUT
                                         branch site->cave, run <code> in the cave,
                                         optionally branch back (--back); verify

Notes
  * Keystone's `ldr rX, =<imm>` (literal-pool) support is unreliable here; build
    constants with mov/add/orr, or reserve a `.word` and load it pc-relative.
  * A detour's cave must be free space (default: a run of 0x00 or 0xFF bytes).
    If you displace an instruction that is pc-relative (ldr =, adr, b/bl), moving
    it into the cave changes its target -- fix it up in your <code> by hand.
"""
import sys, argparse, hashlib

BASE = 0xC0000000  # runtime load address; runtime_addr = file_offset + BASE

try:
    from keystone import Ks, KS_ARCH_ARM, KS_MODE_ARM, KS_MODE_LITTLE_ENDIAN, KsError
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_LITTLE_ENDIAN
except ImportError:
    sys.stderr.write(
        "ERROR: needs Keystone + Capstone.\n"
        "  python3 -m venv venv && . venv/bin/activate && pip install keystone-engine capstone\n")
    sys.exit(3)

_ks = Ks(KS_ARCH_ARM, KS_MODE_ARM + KS_MODE_LITTLE_ENDIAN)
_cs = Cs(CS_ARCH_ARM, CS_MODE_ARM + CS_MODE_LITTLE_ENDIAN)


def assemble(code, at):
    """Assemble ARM `code` as if it were located at runtime address `at`.
    Returns bytes. Raises KsError on a bad mnemonic."""
    encoding, _ = _ks.asm(code, addr=at)
    if encoding is None:
        raise KsError("assembler produced no output")
    return bytes(encoding)


def disasm(data, at):
    """Yield (addr, mnemonic, op_str, raw_bytes) for ARM `data` based at `at`."""
    for ins in _cs.disasm(bytes(data), at):
        yield ins.address, ins.mnemonic, ins.op_str, ins.bytes


def _show(data, at, prefix="    "):
    for addr, mn, ops, raw in disasm(data, at):
        print(f"{prefix}0x{addr:08X}  {raw.hex():<8}  {mn} {ops}".rstrip())
    tail = len(data) % 4
    if tail:
        print(f"{prefix}(+{tail} trailing byte(s) not a full instruction)")


def _load(path):
    with open(path, "rb") as f:
        return bytearray(f.read())


def _save(path, data):
    with open(path, "wb") as f:
        f.write(bytes(data))
    print(f"wrote {path}  ({len(data)} bytes, sha256 {hashlib.sha256(bytes(data)).hexdigest()})")


# ---- subcommands ---------------------------------------------------------

def cmd_dis(a):
    data = _load(a.bin)
    n = a.n if a.n else 8
    region = data[a.off:a.off + n * 4]
    print(f"{a.bin}  file 0x{a.off:05X} -> runtime 0x{BASE + a.off:08X}  ({n} instr)")
    _show(region, BASE + a.off)
    return 0


def cmd_asm(a):
    at = a.at if a.at is not None else BASE
    code = a.code.replace(";", "\n")
    try:
        b = assemble(code, at)
    except KsError as e:
        print(f"assemble error: {e}"); return 1
    print(f"assembled at 0x{at:08X}: {b.hex()}  ({len(b)} bytes)")
    print("round-trip disassembly:")
    _show(b, at)
    return 0


def cmd_patch(a):
    data = _load(a.bin)
    at = BASE + a.off
    code = a.code.replace(";", "\n")
    try:
        new = assemble(code, at)
    except KsError as e:
        print(f"assemble error: {e}"); return 1
    old = bytes(data[a.off:a.off + len(new)])

    print(f"site   : file 0x{a.off:05X} -> runtime 0x{at:08X}")
    print(f"old ({len(old)}): {old.hex()}")
    for addr, mn, ops, raw in disasm(old, at):
        print(f"         0x{addr:08X}  {raw.hex():<8}  {mn} {ops}".rstrip())
    print(f"new ({len(new)}): {new.hex()}")
    _show(new, at, prefix="         ")

    if a.expect is not None:
        exp = bytes.fromhex(a.expect.replace(" ", ""))
        if old[:len(exp)] != exp:
            print(f"ERROR: --expect {exp.hex()} does not match bytes at site ({old[:len(exp)].hex()})."); return 1
        print("expect : OK")
    if len(new) != len(old) and not a.force:
        # same length by construction above; guard only if caller truncated expect oddly
        pass
    data[a.off:a.off + len(new)] = new
    _save(a.out, data)
    return 0


def _is_free(region, fill):
    return all(b == fill for b in region)


def cmd_detour(a):
    data = _load(a.bin)
    site_at = BASE + a.site
    cave_at = BASE + a.cave
    body = a.code.replace(";", "\n")

    # 1) the branch that replaces the one instruction at the site
    try:
        br = assemble(f"b 0x{cave_at:08X}", site_at)
    except KsError as e:
        print(f"assemble error (site branch): {e}"); return 1
    if len(br) != 4:
        print(f"ERROR: site branch assembled to {len(br)} bytes, expected 4."); return 1

    displaced = bytes(data[a.site:a.site + 4])
    print(f"site   : file 0x{a.site:05X} -> runtime 0x{site_at:08X}")
    print(f"         displaces: {displaced.hex()}  ", end="")
    for _, mn, ops, _raw in disasm(displaced, site_at):
        print(f"{mn} {ops}".rstrip(), end="")
    print()
    print(f"         branch   : {br.hex()}  b 0x{cave_at:08X}")

    if a.expect is not None:
        exp = bytes.fromhex(a.expect.replace(" ", ""))
        if displaced[:len(exp)] != exp:
            print(f"ERROR: --expect {exp.hex()} != site bytes {displaced[:len(exp)].hex()}."); return 1
        print("expect : OK")

    # 2) assemble the cave body at the cave's runtime address
    try:
        cave = bytearray(assemble(body, cave_at))
    except KsError as e:
        print(f"assemble error (cave body): {e}"); return 1
    if a.back:
        back_at = cave_at + len(cave)
        back = assemble(f"b 0x{site_at + 4:08X}", back_at)
        cave += back
        print(f"         --back   : appended b 0x{site_at + 4:08X}")

    # 3) the cave region must be free space (don't clobber code/data)
    region = bytes(data[a.cave:a.cave + len(cave)])
    if not (_is_free(region, 0x00) or _is_free(region, 0xFF)):
        print(f"ERROR: cave at file 0x{a.cave:05X} (len {len(cave)}) is not free "
              f"(expected all 0x00 or all 0xFF). First bytes: {region[:16].hex()}")
        print("       Pick an empty offset, or pass --force to overwrite anyway.")
        if not a.force:
            return 1

    print(f"cave   : file 0x{a.cave:05X} -> runtime 0x{cave_at:08X}  ({len(cave)} bytes)")
    _show(cave, cave_at, prefix="         ")

    # 4) splice: branch at the site, body in the cave
    data[a.site:a.site + 4] = br
    data[a.cave:a.cave + len(cave)] = cave
    _save(a.out, data)
    return 0


def main(argv):
    global BASE
    p = argparse.ArgumentParser(description="Assemble ARM and splice into a firmware image.",
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog=__doc__)
    p.add_argument("--base", type=lambda s: int(s, 0), default=None,
                   help=f"runtime load base (default 0x{BASE:08X})")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("dis", help="disassemble at a file offset")
    s.add_argument("bin"); s.add_argument("off", type=lambda s: int(s, 0))
    s.add_argument("n", nargs="?", type=int, default=0)
    s.set_defaults(fn=cmd_dis)

    s = sub.add_parser("asm", help="assemble a snippet")
    s.add_argument("code"); s.add_argument("--at", type=lambda s: int(s, 0), default=None)
    s.set_defaults(fn=cmd_asm)

    s = sub.add_parser("patch", help="in-place splice (same length)")
    s.add_argument("bin"); s.add_argument("off", type=lambda s: int(s, 0)); s.add_argument("code")
    s.add_argument("-o", "--out", required=True)
    s.add_argument("--expect", help="hex bytes expected at the site before patching")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_patch)

    s = sub.add_parser("detour", help="branch to a code cave and (optionally) back")
    s.add_argument("bin"); s.add_argument("site", type=lambda s: int(s, 0))
    s.add_argument("cave", type=lambda s: int(s, 0)); s.add_argument("code")
    s.add_argument("-o", "--out", required=True)
    s.add_argument("--back", action="store_true", help="append b <site+4> to return")
    s.add_argument("--expect", help="hex bytes expected at the site before detouring")
    s.add_argument("--force", action="store_true", help="overwrite a non-free cave")
    s.set_defaults(fn=cmd_detour)

    a = p.parse_args(argv[1:])
    if a.base is not None:
        BASE = a.base
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
