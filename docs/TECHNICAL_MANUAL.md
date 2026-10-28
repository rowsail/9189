# Spectracom NetClock 9189 — Technical Manual (reconstructed)

> **Status: DRAFT / work in progress.** This is a community-reconstructed technical
> reference for the Spectracom NetClock 9189 GPS time server, assembled from the running
> unit and analysis of its firmware (app `D9189V104`, boot loader `BOOTV104` v1.0.4).
> It is **not** an official Spectracom document. The 9189 is long end-of-life.
>
> ⚠️ **Authorized use only.** Everything here assumes you own the unit or are authorized to
> service it. Some actions (firmware install, GPS service mode, config resets) can take the
> clock offline or require physical/console access. Comply with applicable law.

## Table of contents
1. [What the device is](#1-what-the-device-is)
2. [Hardware overview](#2-hardware-overview)
3. [How it boots & runs](#3-how-it-boots--runs)
4. [Access channels (how you reach each feature)](#4-access-channels)
5. [Accounts & access control](#5-accounts--access-control)
6. [Web interface (HTTP) reference](#6-web-interface-http-reference)
7. [CLI reference (telnet / serial console)](#7-cli-reference-telnet--serial-console)
8. [GPS receiver & the WinOncore "service mode"](#8-gps-receiver--the-winoncore-service-mode)
9. [Services & ports](#9-services--ports)
10. [Boot Monitor (serial, pre-boot)](#10-boot-monitor)
11. [Determining what's fitted on a unit](#11-determining-whats-fitted-on-a-unit)
12. [Open items / to verify](#12-open-items--to-verify)

---

## 1. What the device is
The NetClock 9189 is a **GPS-disciplined network time server**. It acquires time from a
GPS receiver, disciplines an internal clock, and distributes time over the network (NTP)
and via serial/relay/IRIG outputs. It is managed over HTTP, telnet, serial console, SNMP,
and FTP.

> **⚠ Firmware is common across board variants — features are hardware/option-dependent.**
> A single firmware image (`D9189V104`) runs across the NetClock 91xx family. Every command,
> web page, and menu item documented here **exists in firmware on every unit**, but a given
> board is built with only a subset of the physical outputs/options (e.g. extra serial/remote
> ports, relays, IRIG, dataports). Where the hardware isn't fitted, the corresponding command
> or page is still present but is a no-op, hidden from the menu, or reports an error. **This
> 9189 variant omits some outputs.** Items that depend on installed hardware/options are marked
> **†** below. Treat the presence of a command as "the firmware supports it," not "this board
> has it."

Core software components identified in the firmware:
- **Treck** TCP/IP stack (and Treck FTP server)
- **GoAhead WebServer** (embedded HTTP server, the web UI)
- **SNMP Research** SNMP agent (© 1992–1998)
- Spectracom application modules: Clock, GPS_Caretaker, EventSched, Alarm, Log,
  Supervisor, Network, TelnetProxy, FTPD, and the GoAhead integration (webs)
- **Delta LFS** — Spectracom's log-structured flash file system

## 2. Hardware overview
- **SoC:** Triscend TA7S20 (A7S Configurable System-on-Chip) — **ARM7TDMI** core (ARMv4T)
  plus a configurable logic (CSL) fabric, 208-pin PQFP.
- **GPS receiver:** Motorola **Oncore M12+** (12-channel), spoken to over an internal
  serial link using the Oncore `@@` binary protocol.
- **Flash:** 8 MB external flash (holds boot loader, application, and the Delta LFS).
- **Clock hardware:** RTC chip + EEPROM (accessible via the `clock` CLI group), 1PPS engine.
- **I/O:** multiple serial "data ports"/"remote ports", relay outputs, IRIG output,
  a serial **setup/console** port, and the Ethernet interface.
- **Debug:** JTAG (ARM7TDMI) is present; see the recovery notes for pinout/quirks.

## 3. How it boots & runs
1. Power on → **BOOTV104** boot loader runs. It can be interrupted at the console to enter
   the [Boot Monitor](#10-boot-monitor) ("press any key to escape to shell mode").
2. The boot loader copies the application image to RAM at base `0xC0000000` and jumps to it.
3. The application brings up board hardware (LED/timer/SPI/ADC/DAC/relay), the Treck
   stack and network, the GoAhead web server, telnet, FTP, SNMP, the GPS caretaker, the
   clock engine, logging, and the supervisor — then runs normally.

## 4. Access channels
How you reach the system, and what each channel is good for:

| Channel | Transport | Use |
|---------|-----------|-----|
| **HTTP (web UI)** | TCP 80, GoAhead | Primary configuration & status GUI |
| **Telnet (CLI)** | TCP 23 | Full command-line interface (can be disabled) |
| **Serial console (CLI)** | RS-232, **9600 8N1** | Same CLI as telnet; always available; `Account:` login |
| **Serial (Boot Monitor)** | RS-232, 9600 8N1, pre-boot | Flash/debug before the app starts |
| **FTP** | TCP 21, Treck FTP | File access (logs, histograms, config/image transfer) |
| **SNMP** | UDP 161 (traps 162) | Monitoring and some configuration via MIB |
| **NTP** | UDP 123 | The time service itself (server; unicast & multicast) |
| **Serial/Remote/Data ports** | RS-232 | Time-code / dataport outputs |
| **GPS service passthrough** | web toggle → serial setup port | Direct link to the M12+ receiver (WinOncore) |

> **Note on the web UI:** the GoAhead server is a 2003-era implementation. It mints a
> single session (`SPEC=nn` cookie) and allows **one connection at a time**. A small local
> reverse proxy (`tools/netclock_proxy.py`) makes it usable from a modern browser.

## 5. Accounts & access control
The firmware ships four built-in account tiers (managed with the `sec` CLI group and the
web login pages):

| Account | Role |
|---------|------|
| `user`  | lowest privilege / read-oriented |
| `config`| configuration |
| `admin` | administrative (required for most config writes) |
| `debug` | highest; unlocks debug/service functions and the Boot Monitor flash commands |

- **Write-privilege gating:** config-changing web actions check the session's privilege and
  refuse with *"Read-only mode is not qualified…"* / *"Only ADMIN mode is qualified to update
  … config"* when the session lacks write rights. Log in as **admin** before changing config.
- The CLI `sec` group can show the current level (`sec level`), list/rename accounts
  (`sec account`), set passwords (`sec password`), and dump account info (`sec display`).

### Permission levels (CLI)
Each CLI command carries a required-level field. Verified on-device (logged in as `admin`,
then `debug`), the levels map to the account tiers:

| Level | Tier | |
|------:|------|--|
| 0 | **User** | read-only / lowest |
| 1 | **Config** | |
| 2 | **Admin** | |
| 3 | **Debug** | highest |

A command runs only if your session level is **≥** the command's required level. Where each
CLI group sits:

| Required | CLI groups |
|----------|------------|
| 0 — User | `net`, `sec level`/`sec help` |
| 1 — Config | `sec display` |
| 2 — Admin | `sec account`, `sec password`, `update` (`csl`/`boot`) |
| 3 — Debug | `ftp`, `telnet`, `snmp`, `ntp`, `clock`, `log`, `gps`, `rly`, `sup`, `web` |

**Consequence — most status/service CLI groups are debug-only.** Logged in as **admin**,
`net`, `sec`, and `update` work, but `gps`, `sup`, `log`, `clock`, `ftp`, `telnet`, `snmp`
and `ntp` all return *"Authorization Failure, command failed"* — they need **`login debug`**.
So reading GPS status (`gps record`), system status (`sup system`) or the logs over the CLI
requires the debug account.

**Web vs CLI asymmetry.** The web UI only needs **admin** (level 2) to manage FTP/telnet/SNMP/NTP
(the `netconfig` FTP/telnet toggles, `ntpu`, `snmpu`) — so routine service configuration is
easiest from the web. The equivalent **CLI** groups are gated at **debug** (level 3).

## 6. Web interface (HTTP) reference
The web UI is served from `/goforms/<name>`. Pages come in pairs: a **display** form
(`gpsconfig`, `netconfig`, …) and an **update** handler (`gpsu`, `netu`, …, suffix `u`)
that the form POSTs to. Reaching the UI: `GET /` → `/goforms/index` → *Enter main page*
(POST `/goforms/main`) → frameset (menu + content).

**Main configuration/status pages** (reachable from the menu):

| Area | Display page | Update |
|------|--------------|--------|
| Network | `netconfig` | `netu` |
| NTP | `ntp` | `ntpu` |
| SNMP | `snmp` | `snmpu` |
| GPS config (antenna/cable) | `gpsconfig` | `gpsu` |
| GPS signal status | `gpsstatus` | — |
| GPS log / report | `gpslog`, `gpsreport` | — |
| Alarms | `alarmconfig` | `alarmu` |
| Events | `eventconfig` / `eventid` | `eventu` |
| Relays † | `relayconfig` | `relayu` |
| Serial ports (port 2 †) | `serial1` / `serial2` | `serial1u` / `serial2u` |
| Remote ports † | `remote1` / `remote2` | `remote1u` / `remote2u` |
| IRIG † | `irig` | `irigu` |
| Time zone / DST | `autotimezone`, `autodst` | `timezoneu`, `dstu` |
| UTC/leap | `utctime` | `utcu` |
| Logs | `alarmlog`, `eventlog`, `operationlog` | — |
| System status | `system` | — |
| Login / session | `admin_login`, `config_login`, `adminV`, `configV`, `logout`, `exit` | — |
| Factory | `default`, `restore` | — |

**†** = board/option-dependent: present in firmware on all variants; functional only if the matching output/option is installed (otherwise the page may be absent from the menu or report an error).

**Undocumented / unlinked endpoints** (registered but not in the menu — reach by URL):
`sendtosetupport`, `sendtouart` (GPS passthrough, see §8), and the display pages
`irig`, `remote2`, `serial2` (their menu links are conditional on installed options).

## 7. CLI reference (telnet / serial console)
Log in at the `Account:`/password prompt, then use `<group> <subcommand> [args]`.
Every group has a `help` subcommand. Reconstructed from the firmware's own help text:

**†** marks groups that control hardware/outputs which may not be fitted on this board.

### `ftp`

- `help` — ftp help - list of ftp commands
- `enable` — ftp enable - turn ftp interface on
- `disable` — ftp disable - turn ftp interface off
- `default` — ftp default - set ftp configuration to default values
- `show` — ftp show - display ftp configuration

### `telnet`

- `help` — telnet help - list of telnet commands
- `enable` — telnet enable - turn telnet interface on
- `disable` — telnet disable - turn telnet interface off
- `default` — telnet default - set telnet configuration to default values
- `show` — telnet show - display telnet configuration

### `snmp`

- `help` — snmp help - list of snmp commands
- `show` — snmp show - display snmp settings
- `enable` — snmp enable - turn on snmp protocol
- `disable` — snmp disable - turn off snmp protocol
- `read` — snmp read [community] - set read community string
- `write` — snmp write [community] - set write community string
- `trap` — snmp trap [name] - set trap community string
- `trapip` — snmp trapip [ip] - set trap destination ip address
- `auth` — snmp auth - set SNMP authorization password
- `priv` — snmp priv - set SNMP privacy password
- `default` — snmp default - set configuration parameters to default values

### `net`

- `help` — net help - list of net commands
- `mask` — net mask mmm.mmm.mmm.mmm - set new network mask
- `ip` — net ip nnn.nnn.nnn.nnn - set new ip address
- `show` — net show - display network configuration to the user
- `default` — net default - set all net parameters back to default values
- `gateway` — net gateway [yes,no] [address] - enable gateway
- `mac` — net mac [xx:xx:xx:xx:xx:xx] - get or set MAC address

### `web`

- `help` — web help - list of net commands
- `exit` — web exit - exit the current connection

### `gps`

- `help` — GPS help - list of net commands
- `record` — gps record - get record
- `leapset` — gps leapset [on/off] - turn on/off leap second set by user
- `setleap` — gps setleap [nn] [mm dd yyyy hh mm ss] - set up leap second status
- `getleap` — gps getleap  - get leap second status
- `gethistogram` — gps gethistogram - get text file for GPS qialification histogram log

### `rly` †

- `help` — rly help - list of event relay scheduler commands
- `open` — rly open # - Open a relay
- `close` — rly close # - Close a relay
- `set` — rly set # <type> - Set a relay to be of <type>
- `get` — rly get # - Get the type of a relay
- `dump` — rly dump - Dump the current relay states and type settings

### `clock`

- `help` — clock help - list of clock commands
- `get` — clock get - Get the system clock
- `set` — clock set MM DD YYYY hh mm ss - set the system clock
- `getrtc` — clock getrtc - Get RTC Chip information
- `readrtc` — clock readrtc - Read RTC RAM location
- `writertc` — clock writertc - Write RTC RAM location
- `readprom` — clock readprom - Read EEPROM location
- `writeprom` — clock writeprom - Write EEPROM location
- `sync` — clock sync - Tell dataport micros to sync
- `unsync` — clock unsync - Tell dataport micros to free run
- `holdover` — clock holdover [seconds] - Set or display the current holdover time

### `log`

- `help` — log help - list of log commands
- `show` — log show [s|u|a|t|o] - Display the contents of the log
- `clear` — log clear [s|u|a|t|o] - Clears the contents of the log
- `get` — log get [s|u|a|t|o] <handle> - Display log record for <handle>

### `sec`

- `account` — sec account <Account-Name> <new-name>
- `display` — sec display - dump out contents of accounts and passwords
- `level` — sec level - show the current security level
- `password` — sec password <Account-Name> <old-password> <new-password>
- `help` — sec help - list of sec sub-commands and detailed information on each

### `sup`

- `help` — sup help - Used to get detailed help for supervisor commands
- `system` — sup system - used to get the system status
- `msg` — sup msg - used to send a message to the supervisor
- `activate` — sup activate <component number>
- `deactivate` — sup deactivate argument <component number>
- `debug` — sup debug

### `update`

- `help` — update help - list each subcommand and its description
- `csl` — update csl <filename> - install a new CSL image
- `boot` — update boot <filename> - install a new bootload image

### `ntp`

- `help` — ntp help [command]- used to get help about NTP commands
- `enable` — ntp enable - used to get enable NTP
- `disable` — ntp disable - used to get disable NTP
- `default` — ntp default - used to set NTP configuration to default values
- `unicast` — ntp unicast [on|off] - display/toggle NTP unicast response
- `multicast` — ntp multicast [on|off] - display/toggle NTP multicast
- `mcauth` — ntp mcauth [on|off] - display/toggle NTP multicast authentication
- `mckey` — ntp mckey [keyid] - display/set NTP multicast authorization key
- `interval` — ntp interval [secs] - display/set NTP multicast interval
- `secure` — ntp secure [on|off] - display/toggle NTP authorization
- `setkey` — ntp setkey index keyid keystring - used to set an NTP key
- `getkey` — ntp getkey [index] - used to get an NTP key setting
- `deletekey` — ntp deletekey index - used to erase an NTP key setting


> The `update` group (`update csl <file>`, `update boot <file>`) installs a new CSL
> (Triscend logic) image or boot loader and is a privileged operation — use with care.

## 8. GPS receiver & the WinOncore "service mode"
The GPS solution is computed by the **Motorola Oncore M12+** receiver; the application's
`GPS_Caretaker` supervises it over an internal serial link using the Oncore `@@` binary
protocol. Normal GPS configuration (antenna cable delay, position, alarm thresholds, leap
seconds) is done from the `gpsconfig` web page and the `gps` CLI group.

**Direct access to the receiver (service mode):** the firmware can re-route the receiver's
serial link from the internal UART to the external **serial setup/console port**, so a PC
running Motorola **WinOncore** (or any terminal speaking the Oncore protocol) can talk to
the M12+ directly.

- **Enter service mode:** `GET /goforms/sendtosetupport` — the page confirms
  *"Now you can use WinOncore to communicate with the GPS receiver"* and warns that changes
  you send have side effects on timekeeping.
- **Leave service mode:** `GET /goforms/sendtouart` (also offered as a **UART** link on the
  status page while service mode is active).
- **Requires an admin/write-privileged web session.** There is **no button for it in the
  menu** — you reach it by URL. The GPS Signal Status page (`gpsstatus`) only shows the
  **exit** ("UART") link, and only while service mode is already active.
- Internally this toggles a hardware serial-multiplexer bit, connecting the M12+ either to
  the CPU (normal) or to the setup port (service mode). **While service mode is active the
  clock is not reading the receiver**, so return to UART when finished.

This is the supported way to send commands (e.g. the Oncore mask-angle command `@@Ag`)
directly to the receiver for testing. Note that the application re-initializes the receiver
at each boot, so changes made interactively may not persist across a power cycle.

**There is no network-only path to the receiver.** Two things make this a
physical-serial-only feature:

- *Only HTTP can throw the switch.* The mux toggle is called exclusively from the
  `sendtosetupport` / `sendtouart` web handlers. **No telnet/CLI command flips it** — the
  `gps` command group only dispatches its fixed subcommands (`record`, `leapset`, `setleap`,
  `getleap`, `gethistogram`, `help`); none sends raw bytes to the receiver, and `sup debug`
  toggles an unrelated hardware bit, not the GPS mux.
- *It's a hardware crossbar, not a tunnel.* Entering service mode cross-connects the M12+'s
  serial lines to the **physical setup/console RS-232 port** at the hardware level; the CPU
  leaves that path. HTTP only throws the switch — it does not carry the receiver's bytes, and
  neither does telnet.

**So the only way to send `@@` commands is:** an **admin HTTP** request to
`sendtosetupport` **plus a PC physically cabled to the setup serial port** (WinOncore or a
raw Oncore terminal), then `sendtouart` when finished. Telnet alone cannot do it, and
telnet+HTTP cannot do it — HTTP throws the switch, but the data only exists on the physical
port. (The setup port normally carries the serial-console CLI; while service mode is active
it speaks GPS instead, but the network telnet CLI keeps working independently.)

## 9. Services & ports

| Service | Port | Implementation | Notes |
|---------|------|----------------|-------|
| NTP | UDP 123 | Spectracom | Server; unicast + multicast; optional auth & keys (`ntp` CLI / `ntpu` web). *Verified up; reports unsynchronized until the GPS has a fix.* |
| HTTP | TCP 80 | GoAhead WebServer | One session at a time; `SPEC` cookie. *Verified open.* |
| Telnet | TCP 23 | Treck + TelnetProxy | CLI; can be enabled/disabled (`telnet` group). *Verified open.* |
| FTP | TCP 21 | Treck FTP server | Banner *"220 Treck FTP server ready."* (verified); enable/disable (`ftp` group) |
| SNMP | UDP 161 / 162 | SNMP Research | Communities (read/write), traps; ADMIN required to change. *Disabled by default — enable via `snmp enable`.* |
| Serial console | RS-232 9600 8N1 | — | CLI + Boot Monitor |

Each network service (NTP, telnet, FTP, SNMP) can be independently enabled/disabled and
reset to defaults from its CLI group or web page.

### What SNMP exposes
Agent: **SNMP Research** EMANATE 15.1.1.8 — SNMPv1 / v2c / v3. **Disabled by default**
(`snmp enable` to turn it on; changing SNMP config needs ADMIN).

**Read / monitoring**
- Standard **MIB-II** (system, snmp groups). `sysObjectID` = `1.3.6.1.4.1.100.1.1.1`,
  `sysDescr` = *"...agent from SNMP Research, Inc."*
- A small **Spectracom enterprise MIB** at `1.3.6.1.4.1.100.1` that reports **alarm status**
  only - `...1.2.1.1-3.0` (major/minor/none and alarm detail) plus an alarm table at
  `...1.2.2.1`. These are **read-only**, and are the same varbinds carried in alarm traps.

**Traps out** - alarm-condition traps to configured destinations (default target
`192.168.1.2`), as v1, v2c and v3.

**Writable over SNMP** (with the write community / v3 user):
- MIB-II system identity: `sysContact`, `sysLocation`, `sysName`.
- The **agent's own configuration** (all `nonVolatile`/read-create framework tables):
  communities, VACM groups / access / views, trap-target addresses & params, notify
  entries, and SNMPv3 USM users.

**Not configurable over SNMP** - the clock's operation (network, GPS, NTP, serial/relay,
time/DST, alarm thresholds). There is **no Spectracom configuration MIB**; those settings
are web/CLI only.

**Access model (defaults):** community `public` -> read-only over the whole tree;
`private` -> read + write; an SNMPv3 USM user `SnmpUser` has full read/write/notify - all at
**noAuthNoPriv**, so the write path is only as strong as those trivial community strings.
Harden it, or leave SNMP disabled, if the unit is exposed.

## 10. Boot Monitor
`BOOTV104` includes a serial **Boot Monitor** reached by pressing a key during boot
("escape to shell mode"). It provides low-level flash and memory commands (sector list,
dump/edit/fill/copy/search, checksum/crc, erase, S-record upload, jump). It authenticates
at the console `Account:` prompt and the flash-write commands require **debug-level**
access. This is the serial route for reading/erasing/programming flash without JTAG.
(Credentials and the flashing procedure are covered in the project README / recovery notes.)

## 11. Determining what's fitted on a unit
Because the firmware is common across the family (see §1), the reliable way to tell what a
particular board actually has is the **System Status** page (web `system`) — its
**self-test** section only lists subsystems that are installed. A subsystem absent from the
self-test is not fitted, even though its config page/commands still exist.

**Worked example (the unit this manual was built against):**

```
Product Name ......... Spectracom Model 9189
Application .......... D9189V104.bin  rev 1.0.4  (8/27/2003)
Boot Monitor ......... rev 1.0.4
System Test Result:
  PCB Test ........... PASSED (PCB rev 2)
  CSL Test ........... PASSED (CSL rev 7)
  RTC Test ........... PASSED
  Relay/Fan Test ..... PASSED
  GPS Self-Test ...... PASSED
  Serial 1 ........... PASSED (2.03)
  Remote 1 ........... PASSED (2.03)
```

Reading that self-test, this board's fitment is:

| Subsystem | Fitted? | Evidence |
|-----------|---------|----------|
| GPS receiver (M12+) | yes | GPS Self-Test listed |
| RTC / EEPROM | yes | RTC Test listed |
| CSL (Triscend logic) | yes | CSL Test (rev 7) |
| Relays (x3) | yes | Relay/Fan Test listed; `relayconfig` shows Relay 1-3 |
| Serial port 1 | yes | Serial 1 listed (micro v2.03) |
| Remote port 1 | yes | Remote 1 listed (micro v2.03) |
| **Serial port 2** | no | not in self-test (page `serial2` still renders) |
| **Remote port 2** | no | not in self-test (page `remote2` still renders) |
| **IRIG output** | no | not in self-test (page `irig` still renders) |

So on this unit the **†** items IRIG, Serial 2, and Remote 2 exist in firmware/UI but are
**not installed** — their pages load and commands run, but they control hardware that isn't
present. Relays *are* fitted here. Check the self-test on any given unit before relying on a
**†** feature.

## 12. Open items / to verify
- Ports verified on the running unit: FTP 21, telnet 23, HTTP 80 open; NTP 123 up
  (unsynchronized without a GPS fix); SNMP 161 not responding (disabled by default). ✓
- Fitment method verified: the `system` self-test enumerates installed subsystems (§11). ✓
- ✅ `sec` permission levels mapped on-device: 0=User, 1=Config, 2=Admin, 3=Debug; a command needs session level ≥ its field. Web config writes need ≥ 2 (admin); most status/service CLI groups need 3 (debug). See §5.
- Map the remaining update handlers (`*u`) field-by-field for a complete config schema.
- Confirm Oncore `@@Ag` behaviour and persistence via service mode on-device.

---
*Reconstructed by analysis of an owned, end-of-life unit for repair/interoperability.
Corrections welcome.*


---

## Appendix A — Configuration field reference

Every `*u` update handler enforces the same gate: it checks the write-privilege flag and the
global config-lock, then requires **privilege level ≥ 2** — a read-only session is answered
with *"Read-only mode is not qualified…"* and nothing is written. It then reads each form
field by name (the names below are the actual POST field names) and validates before saving.

| Handler ← page | Fields (POST names) |
|----------------|---------------------|
| `netu` ← netconfig | `ip1-4`, `mask`, `gateoption`+`gate1-4`, `telnet`, `ftp` — (telnet/FTP enable live on the network page) |
| `ntpu` ← ntp | `NTPsetup`, `NTPunicast`, `NTPmulticast`, `NTPsecure`, `NTPMD5`, `keyid`, `interval` |
| `snmpu` ← snmp | `snmp` (enable), `readComm`, `writeComm`, `trapComm`, `trapIP` |
| `gpsu` ← gpsconfig | `cable` (0–999999 ns), `Lat`/`Long`, `lat{degree,minute,second}`, `long{degree,minute,second}` — position refused while the receiver has a 2D/3D fix |
| `serial1u`/`serial2u` ← serial1/2 † | `baudRate`, `dataFormat`, `requestChar`+`userdefinedchar`, `timezone`, + DST block |
| `remote1u`/`remote2u` ← remote1/2 † | `baudRate`, `dataFormat`, `timezone` (remote1), + DST block |
| `irigu` ← irig † | `irigF`, `level`, `carrier`, `irigSignature`, + DST block |
| `relayu` ← relayconfig † | `R1`, `R2`, `R3` (per-relay mode) |
| `alarmu` ← alarmconfig | `gpsmajor`/`mjgnumber`/`mjg{day,hour,min,sec}`, `faultmajor`/`sf{day,hour,min,sec}`, `gpsminor`/`mignumber`/`mig{day,hour,min,sec}` |
| `utcu` ← utctime | `utcyear`, `utcmonth`, `utcday`, `utchour`, `utcminute`, `utcsecond` |
| `timezoneu`/`dstu` ← autotimezone/autodst | `timezone`, `dstOption`, `dstRegion`, + DST block |
| `eventu` ← eventconfig/eventid | `eventId` (select first), then state / relay / schedule (weekday · mDay · yDay + time) |

**DST block** (shared by the serial, remote, IRIG and timezone pages): `dstOption`
(none / by-week / by-date), `dstRegion`, and start/end rules —
`weekNumIn weekDayIn monthNoIn_1 hourIn_1 minIn_1` / `…Out…`, the `_2` set for by-date
(`dayIn`, `dayOut`, `monthNoIn_2`, …), and `hourChange_1`/`minChange_1` for the offset.

† board/option-dependent (see §11). Field names are the firmware's own, read directly from
the forms; this is the schema a script would POST to configure the unit over HTTP.
