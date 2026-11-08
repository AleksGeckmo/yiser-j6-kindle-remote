# Yiser-J6 ring remote → real keyboard keys (for a Kindle page turner)

The **Yiser-J6** is a cheap Bluetooth "TikTok scroller" ring remote. Out of the box it
pretends to be a **touchscreen**: every button press is sent as a finger swipe or tap,
so on Linux (and a jailbroken Kindle running
[kindle-hid-passthrough](https://github.com/zampierilucas/kindle-hid-passthrough))
every button arrives as the same `BTN_TOUCH` (code 330) and only the coordinates differ.

This repo documents how the remote works inside, how to get into its bootloader with a
Raspberry Pi Pico, how its firmware is laid out and encrypted, and a **small data-only patch**
to the original firmware that makes it send ordinary keyboard keys:

| Button | Short press | Long press |
|---|---|---|
| Up / Down | Up / Down arrow | auto-repeat |
| Left / Right | Left / Right arrow | same key |
| Centre | Enter | Enter |
| Button 2 | Space | — |
| Button 1 | power on/off (unchanged) | — |

Nothing else changes: power handling, charging and Bluetooth are the vendor's own code.

> **Do this only on hardware you own, and back up first.** Flashing can leave the remote
> non-booting; the chip's ROM bootloader is always available to restore your backup, but you
> need the wiring below to reach it. No firmware images are included here — you patch your own dump.

---

## 1. Hardware

* SoC: **Jieli AC6323A** (QFN20), marked `BP3F034-23A4` — the `23A4` after the dash is the part
  (AC63**23A**, 4 Mbit flash). Jieli family **BD19 / AC632N**, CPU arch `q32s`.
* 24 MHz crystal, PCB antenna, 40 mAh LiPo on pads `B+`/`B-`, USB-C (charge only — its data
  pins are **not** connected to the chip).
* Board silkscreen: `yiser-J6 V1.x`, `2023-05-30`.

AC6323A pins that matter (pin 1 = VBAT; numbering continues counter-clockwise seen from the top):

| Pin | Name | On this board |
|---|---|---|
| 1 | VBAT | battery +, also a round test pad (~4.1 V) |
| 2 | LDOIN / PP0 | 5 V from USB-C (connector pad 5) + a test pad |
| 3 | VDDIO | ~3 V rail |
| 11 | USB0DM (D−) | **test pad** (bare, centre of the board) |
| 12 | USB0DP (D+) | **test pad** right next to the D− pad |
| PB7, PA7, PA8, PA0, PA1, PA2, PA9 | GPIO | the 7 buttons (to GND); PA9 = button 1 / power |

The D+/D− test pads + VBAT + GND are the factory programming points. You need them.

## 2. How the stock firmware works

The firmware is Jieli's SDK demo **`apps/hid/examples/keypage`** (a "page turner") modified by the vendor.

**HID report map (non-iOS hosts)** — three collections:

| Report ID | Collection | Use |
|---|---|---|
| 1 | Digitizer (touch, X/Y 0..1000) | all short presses (swipes and taps) |
| 3 | Consumer control, 24 one-bit fields | long presses (volume, prev/next track, play) |
| 4 | Keyboard (modifiers + 1 key) | never used |

There is a second map for iOS hosts (mouse-based); it is not touched here.

**Button scripts.** Every press plays a small *script* stored as plain data in `app.bin`
(17 slots of 84 bytes at `app.bin+0x132E4`):

```
u16 slot_index, u16 step_count, then up to 10 x { u16 x, u16 y, u16 action, u16 delay_ms }
action 0x12 = touch down/move, 0x13 = touch up (digitizer report)
action 0x04..0x10 = set one media-key bit (report 3), 0x0C = release
```

Slots: #0 down swipe, #1 up, #2 right, #3 left, #4 centre tap, #5 double-tap ("like"),
#6–#10/#16 media keys, #11/#13–#15 button 2. The axes are flipped: "up" is Y rising.

**Media-key descriptor** (report 3, 80 bytes at `app.bin+0x12922`): bit *n* of the 24-bit report
is the *n*-th Usage in the descriptor. Measured action code → bit on this firmware:

| Action | 0x04 | 0x06 | 0x07 | 0x08 | 0x09 | 0x0B | 0x10 |
|---|---|---|---|---|---|---|---|
| Bit | 14 | 12 | 11 | 16 | 15 | 7 | 17 |

Long presses: left → bit 11, right → 12, centre → 14, up → 15 (repeating), down → 16.

## 3. The patch (data only)

1. **Re-label the 24 media-key bits as keyboard usages**: put `Usage Page (Keyboard)` inside the
   collection and replace each Usage with a keyboard usage — bits 7 & 11 → Left, 12 → Right,
   14 → Enter, 15 → Up, 16 → Down, 17 → Space, the rest → 0. Same length (80 bytes), so nothing moves.
2. **Point the short-press scripts at those bits** (one step + release each):
   left 0x0B, right 0x06, up 0x09, down 0x08, centre 0x04, double-centre 0x04 twice, button 2 0x10.

`patches/yiser_j6_keys.json` is exactly this (offsets into the decrypted `app.bin`).
`tools/make_keys_patch.py` regenerates it. A stricter variant
(`yiser_j6_keys_keyboard_only.json`) replaces the whole 201-byte report map with a single
keyboard collection (no touchscreen at all); it was not needed in practice and is untested on hardware.

The flash changes are 3 × 4 KB sectors (`0x02000`, `0x14000`, `0x15000`).

> The action→bit table above is what this firmware version did. **Check yours** with
> `pc/remote_logger.py` (press each button a different number of times so the log labels itself)
> before trusting the patch on a different remote.

## 4. Getting into the bootloader (Raspberry Pi Pico / Pico 2)

Jieli's ROM enters USB download mode when it receives the **USB_KEY** on the USB lines right after
power-up: 16-bit `0x16EF`, MSB first, data latched on the clock's rising edge, ~25–50 kHz, repeated
until the chip pulls both lines low. Sources disagree on which line is the clock, so
`pico/pico_usb_key.py` sends **both orders alternately** — that worked first try.

Wiring (battery **disconnected** — the Pico powers the chip so it can power-cycle it):

```
Pico GP2 --[1k-1.5k]--+-- D+ pad (pin 12)
Pico GP3 --[1k-1.5k]--+-- D- pad (pin 11)      cut USB cable: green -> D+, white -> D-,
Pico GND -------------+-- GND (any ground pad)                black -> GND, RED UNUSED
Pico GP6 ----------------- VBAT (B+ / VBAT pad)
```

Run (MicroPython, e.g. `mpremote exec "import pico_usb_key as k; k.enter()"`): GP6 power-cycles the
chip, the key is sent for 150 ms, the lines are released, and the chip stays powered. Windows then
shows **`BD19 UBOOT1.00 USB Device`** (USB `4C4A:3442`) as a 0-byte drive.
**Never let Windows format it.**

Notes:
* A Pico GPIO (~12 mA) is enough for the bootloader, **not** for the normal firmware (radio).
  Run the normal firmware on the battery — but never connect the battery and GP6 at the same time.
* Keep the Pico's data pins high-impedance when idle: driving them back-feeds the chip and stops it
  from powering off cleanly.

## 5. Back up, patch, flash

Use kagaimiq's [jl-uboot-tool](https://github.com/kagaimiq/jl-uboot-tool) (its BD19 loader works on
this chip; the tool lists AC632N as "unknown"). On Windows run it from **PowerShell** — Git Bash
mangles the `\\.\D:` device path. It prints the chip key and the flash ID (here SPI NOR `0xCD7113`,
512 KB).

```powershell
python jluboottool.py --device \\.\D: "read 0 0x80000 backup1.bin" exit
# enter the bootloader again, read a second copy, and compare the two (they must be identical)
```

Patch your own backup and write only what changed:

```bash
python tools/jl_unpack.py backup1.bin <chipkey-hex> unpacked     # inspect / verify CRCs
python tools/jl_repack.py backup1.bin <chipkey-hex> patches/yiser_j6_keys.json patched.bin
#  -> prints the changed 4 KB sectors and writes patched.bin.sector_XXXXX.bin for each
```

```powershell
python jluboottool.py --device \\.\D: "write 0x2000 patched.bin.sector_02000.bin" "write 0x14000 patched.bin.sector_14000.bin" "write 0x15000 patched.bin.sector_15000.bin" exit
```

Read the sectors back and compare before you trust them.

**Then: after power is connected, the remote stays OFF until you hold button 1.**
(That cost hours — every "dead firmware" before it was simply switched off.)

## 6. Firmware format notes (JLFS / "new firmware format")

* Flash header (32 B at 0x0) and the top-level entries (`uboot.boot`, `isd_config.ini`,
  `app_dir_head`, `key_mac`) are each scrambled with Jieli's **ENC** cipher, key `0xFFFF`
  (XOR with a CRC-16/0x1021 LFSR keystream). Entry = `<HHIIBBH16s>`: hdr CRC16, data CRC16,
  offset, size, flags, reserved, index, name. CRC16 = poly 0x1021, init 0.
* The app area (`app_dir_head` → flash 0x2000) is encrypted with the **chip key** using the SFC
  scheme: ENC per 32-byte block with key `chipkey ^ ((addr - 0x2000) >> 2)`.
* App area = `app_area_head` (offset field = entry point `0x1E00120`) containing `app.bin`,
  `cfg_tool.bin`, `VM`, `PRCT`, `BTIF`; followed — **unaligned, as the last entry (index 1)** —
  by `p11_code.bin` (4 KB, low-power core code the app loads at boot). Miss it and nothing runs.
* `app_area_head`'s data CRC covers everything after its header up to its `size`; the `app.bin`
  entry carries the CRC16 of `app.bin`. `jl_repack.py` recomputes all of it.
* The bootloader (`uboot.boot`) is byte-identical to the one in Jieli's AC63 SDK
  (`cpu/bd19/tools/uboot.boot`), and the stock `cfg_tool.bin` is the SDK default.

`tools/jl_build_image.py` drops a different `app.bin` into the original layout (it rebuilt the
stock firmware byte-for-byte as a self-test). Custom SDK builds booted far enough to be
switched on but were abandoned in favour of the data patch.

## 7. Kindle / KOReader setup

* After flashing, the host must re-read the descriptor: in KOReader → Settings → Network →
  **BT Manager – HID Passthrough → Debug → Clear descriptor cache**, then reconnect the remote
  (or delete `kindle_hid_passthrough/cache/<remote address>.json` — **not** `pairing_keys.json`).
* In **Key mappings → Yiser-J6**, set **"Handled by: Button Mapper, exclusive"** and bind the keys.
  With the default "Automatic", KOReader grabs the now keyboard-like remote and applies its own
  defaults instead of your bindings.
* Windows keeps its own cached copy of the old descriptor (it keeps showing media keys) — re-pair
  there if you care.
* The remote drops the Bluetooth link when idle; the first press after idle may only wake it.

## 8. Tools in this repo

| File | What |
|---|---|
| `tools/jl_unpack.py` | decrypt + list a JLFS flash dump (header, entries, app area) |
| `tools/jl_repack.py` | apply a JSON patch to the decrypted `app.bin`, fix CRCs, re-encrypt, emit changed sectors |
| `tools/make_keys_patch.py` | generates `patches/*.json` |
| `tools/hid_desc_dump.py` | pretty-print HID descriptors found in `app.bin` |
| `tools/jl_build_image.py` | put a different `app.bin` into the original layout (adds `p11_code.bin`, can move VM) |
| `pico/pico_usb_key.py` | MicroPython: USB_KEY bootloader entry, power cycling, line listener, PIO UART capture |
| `pc/remote_logger.py` | Windows Raw Input logger (mouse/keyboard/HID reports with device IDs) |
| `pc/hid_caps.py` | what Windows thinks each HID collection of the remote can report |

Python 3 + `crcmod` for the tools; MicroPython ≥1.22 on the Pico.

## Credits

* **kagaimiq** — [jielie](https://kagaimiq.github.io/jielie/) docs (USB_KEY, chip markings,
  JLFS, ciphers) and [jl-uboot-tool](https://github.com/kagaimiq/jl-uboot-tool) (MIT); the cipher
  routines here are reimplemented from that work.
* **Jieli** — the public [AC63 Bluetooth SDK](https://github.com/Jieli-Tech/fw-AC63_BT_SDK)
  (the `keypage` example and the AC6323A datasheet explain most of the firmware).
* **zampierilucas** — [kindle-hid-passthrough](https://github.com/zampierilucas/kindle-hid-passthrough)
  and kindle-button-mapper.

Reverse-engineered on hardware I own, for interoperability. Not affiliated with Yiser or Jieli.
