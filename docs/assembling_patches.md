# Assembling and splicing ARM patches (NetClock 9189 / D9189V104)

## Can you disassemble to assembly and reassemble back to a binary?

At the instruction level, yes — that is what patching this firmware *is*. A whole-image
`disassemble -> reassemble` round-trip, however, is the wrong goal here:

- **Byte-identical whole-image round-trip** is achievable but pointless. You would have to
  pin the layout (emit every instruction as its exact encoding or `.word 0x…`, every data
  region as `.byte`/`.word`, with `.org` so nothing moves) — i.e. re-emit the original bytes
  in a complicated way, for zero gain.
- **A freely-editable whole-image rebuild** is *not* practical. The application is hardwired
  to load at `0xC0000000` and is full of absolute pointers living in literal pools (e.g. the
  Oncore command table at `0xC00A57B8`), with **no relocations and no symbols**. Editing code
  and letting an assembler re-lay-out shifts every later instruction, so every baked-in pointer
  and every pc-relative load breaks, with nothing to fix them up. You cannot "edit a line and
  rebuild" like normal source.
- Two more hazards for a stripped ARM blob: **code/data ambiguity** (the disassembler must
  classify every byte — code vs literal pool vs jump table vs string) and **encoding ambiguity**
  (several ARM encodings yield the same mnemonic, so a mnemonic-level reassembler often produces
  *functionally equal but byte-different* output — see the example below).

### The technique that works: assemble a snippet, splice it in

Keep the original bytes; change only what you must, preserving the layout:

- **In-place patch** — replace instructions with the **same number of bytes**, so nothing
  downstream moves. (The WNRO fix is four of these; see `WNRO_FTP_patch_howto.md`.)
- **Code-cave detour** — overwrite one instruction with a branch into free space, run new code
  there, branch back. The body of the image never moves, so every absolute pointer stays valid.

`tools/arm_splice.py` does both, assembling at each instruction's real **runtime** address
(file offset + `0xC0000000`) so branches resolve correctly, and disassembling whatever it is
about to write so you can see the exact instructions first.

## Requirements

    python3 -m venv venv && . venv/bin/activate
    pip install keystone-engine capstone

(No ARM cross-toolchain is required. The tool contains no vendor code; run it on your own dump.)

## Usage

Disassemble to find your site (file offset -> runtime address shown):

    arm_splice.py dis D9189V104.bin 0xBCF0 6

Try an encoding without touching a file:

    arm_splice.py asm "add r3,r3,#0x24000000; add r3,r3,#0xEA0000; mov r0,r3" --at 0xC000BCF0

In-place patch (output must stay the same size; `--expect` guards the site):

    arm_splice.py patch D9189V104.bin 0xBCF0 \
      "add r3,r3,#0x24000000; add r3,r3,#0xEA0000; mov r0,r3; mov r1,r4; mov r2,r5" \
      -o D9189V104_patched.bin --expect c0204be2

Code-cave detour (branch site -> cave, run body, `--back` appends the return branch to site+4;
the cave must be free space — a run of 0x00 or 0xFF):

    arm_splice.py detour D9189V104.bin 0xBCF0 0xC1C00 \
      "add r3,r3,#0x24000000; add r3,r3,#0xEA0000" \
      -o D9189V104_detour.bin --back --expect c0204be2

## Gotchas

- **Encoding ambiguity is real.** Keystone encodes `add r3,r3,#0x24000000` as `093383e2`
  (rotate 3 / imm 0x09); the hand-assembled WNRO patch used `243483e2` (rotate 4 / imm 0x24).
  Both are valid encodings of the **same** immediate and run identically — but the bytes differ,
  so a tool-built image will not be sha-identical to a hand-built one. For the exact shipped
  WNRO bytes, `tools/wnro_patch.py` remains the source of truth.
- **`ldr rX, =<imm>` (literal pool) is unreliable** in Keystone here. Build constants with
  `mov`/`add`/`orr`, or reserve a `.word` and load it pc-relative.
- **Displaced pc-relative instructions.** If the instruction you overwrite with a detour branch
  was itself pc-relative (`ldr =`, `adr`, `b`/`bl`), moving it into the cave changes its target.
  Fix it up by hand in your cave body.
- **Verify on hardware.** Byte-correct is not behaviour-correct. As the WNRO work showed, only
  steady-state verification at a real 3D fix caught the coupled gate and leap-second bugs.
