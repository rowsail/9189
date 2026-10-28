# Example (sanitized) configuration

These files illustrate the Spectracom NetClock 9189 on-flash configuration format
(`key=value`, newline-separated, stored log-structured in the Delta LFS — see
`../docs/NetClock_9189_password_recovery_via_JTAG.md`, §11).

**They are illustrative, not from a live unit.** All sensitive values have been replaced:

- `sec.0.cfg` uses the **factory-default passwords** baked into the firmware
  (`admin` → `admin123`, `config` → `config12`), *not* any real unit's credentials.
- `net.0.cfg` uses the `192.0.2.0/24` documentation range (RFC 5737), not a real network.

Real dumps extracted from a device (`dumps/`) contain **live, plaintext credentials** and
are deliberately excluded from this repository. Never commit them.

## Factory-default accounts (from the firmware)

| Account | Default password | Notes |
|---------|------------------|-------|
| `user`   | `user1234`       | read-only |
| `config` | `config12`       | configuration access |
| `admin`  | `admin123`       | full administrator |
| `debug`  | `XD4o5g7b7e6r0T` | hardcoded firmware backdoor — `"Dogbert"` interleaved with `"X457760"` (see report §7.1) |

If you have recovered or reset a unit, **change these immediately** — they are public and
identical across all units of this firmware.

The `debug` password isn't generated per unit; it's a fixed string compiled into the
firmware, built by interleaving **"Dogbert"** (the *Dilbert* character) with `X457760`. A
permanent backdoor hidden behind a cartoon in-joke. As Maurice Moss put it in *The IT Crowd*
("The Red Door", 2006), on finding an engineer who "run the data lines right through the
power supply": **"Amateur hour! I've got tears in my eyes!"** It can't be removed without
reflashing, so isolate these units' management interfaces on a trusted network.
