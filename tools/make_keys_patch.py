# AI-written: this script was written by Anthropic's Claude (Claude Code). See README "AI disclosure".
"""Build the 'real keys' patch for the ORIGINAL Yiser-J6 firmware (data only).

1) Rewrite the media-key descriptor (report id 3, 24 one-bit fields) at app.bin+0x12922 so each bit
   is a KEYBOARD usage instead of a consumer usage. Same length (80 bytes) so nothing else moves.
2) Point the short-press scripts at action codes whose bits now mean the wanted keys.

Measured (probe 2): action 0x04->bit14, 0x06->bit12, 0x07->bit15, 0x08->bit16, 0x09->bit15,
0x0B->bit7, 0x10->bit17. Long presses send: left bit11, right bit12, centre bit14, up bit15, down bit16.
"""
import json, struct, sys

DESC_OFF = 0x12922
KEY = {'left': 0x50, 'right': 0x4F, 'up': 0x52, 'down': 0x51, 'enter': 0x28, 'space': 0x2C}

bit_key = [0x00] * 24
bit_key[7] = KEY['left']      # short left  (code 0x0B)
bit_key[11] = KEY['left']     # long left
bit_key[12] = KEY['right']    # short + long right (code 0x06)
bit_key[14] = KEY['enter']    # short centre (code 0x04) + long centre
bit_key[15] = KEY['up']       # short + long up (code 0x07)
bit_key[16] = KEY['down']     # short + long down (code 0x08)
bit_key[17] = KEY['space']    # button 2 (code 0x10)

desc = bytes([0x05, 0x0C, 0x09, 0x01, 0xA1, 0x01, 0x85, 0x03,   # Consumer Control app collection, report id 3
              0x05, 0x07,                                       # Usage Page (Keyboard) for the fields below
              0x15, 0x00, 0x25, 0x01, 0x75, 0x01, 0x95, 0x18])  # 24 x 1-bit
for u in bit_key:
    desc += bytes([0x09, u])                                    # Usage (keyboard usage id)
pad = 80 - len(desc) - 3
desc += bytes([0x15, 0x00]) * (pad // 2) + (bytes([0x14]) if pad % 2 else b'')   # harmless Logical Min items
desc += bytes([0x81, 0x02, 0xC0])                               # Input (Data,Var,Abs), End Collection
assert len(desc) == 80, len(desc)


def script(idx, steps):
    s = struct.pack('<HH', idx, len(steps)) + b''.join(struct.pack('<HHHH', 0, 0, c, d) for c, d in steps)
    return s + bytes(84 - len(s))


slots = {
    0x132E4: script(0, [(0x08, 35), (0x0C, 35)]),               # down   -> bit16 Down
    0x13338: script(1, [(0x09, 35), (0x0C, 35)]),               # up     -> code 0x09 (bit15 Up; 0x07 measured as bit11)
    0x1338C: script(2, [(0x06, 35), (0x0C, 35)]),               # right  -> bit12 Right
    0x133E0: script(3, [(0x0B, 35), (0x0C, 35)]),               # left   -> bit7  Left
    0x13434: script(4, [(0x04, 35), (0x0C, 35)]),               # centre -> bit14 Enter
    0x13488: script(5, [(0x04, 35), (0x0C, 35), (0x04, 70), (0x0C, 35)]),  # double centre -> Enter x2
    0x13680: script(11, [(0x10, 35), (0x0C, 35)]),              # button 2 -> bit17 Space
}

if len(sys.argv) > 2 and sys.argv[2] == 'keyboard-only':
    # Replace the WHOLE active (non-iOS) report map - digitizer + consumer + keyboard, 201 bytes at
    # 0x128D2 - with ONE plain Keyboard application collection carrying report id 3's 24 bits, so the
    # host sees an ordinary keyboard (no touchscreen, no spare keyboard collection). Same start, same length.
    SET_B_OFF, SET_B_LEN = 0x128D2, 201
    head = bytes([0x05, 0x01, 0x09, 0x06, 0xA1, 0x01, 0x85, 0x03,  # Generic Desktop / Keyboard app, report id 3
                  0x05, 0x07, 0x15, 0x00, 0x25, 0x01, 0x75, 0x01, 0x95, 0x18])
    body = b''.join(bytes([0x09, u]) for u in bit_key)
    tail = bytes([0x81, 0x02, 0xC0])
    fill = SET_B_LEN - len(head) - len(body) - len(tail)
    kb = head + body + bytes([0x15, 0x00]) * (fill // 2) + (bytes([0x14]) if fill % 2 else b'') + tail
    assert len(kb) == SET_B_LEN, len(kb)
    patch = {hex(SET_B_OFF): kb.hex()}
    print('keyboard-only report map (%d B):' % len(kb), kb[:72].hex(' '), '...', kb[-6:].hex(' '))
else:
    patch = {hex(DESC_OFF): desc.hex()}
patch.update({hex(o): s.hex() for o, s in slots.items()})
json.dump(patch, open(sys.argv[1], 'w'), indent=1)
print('descriptor:', desc.hex(' '))
