# AI-written: this script was written by Anthropic's Claude (Claude Code). See README "AI disclosure".
"""Find and pretty-print every HID report descriptor in the decrypted app.bin."""
import sys

app = open(sys.argv[1], 'rb').read()
LO, HI = int(sys.argv[2], 16), int(sys.argv[3], 16)

MAIN = {8: 'Input', 9: 'Output', 11: 'Feature', 10: 'Collection', 12: 'End Collection'}
GLOBAL = {0: 'Usage Page', 1: 'Logical Min', 2: 'Logical Max', 3: 'Physical Min', 4: 'Physical Max',
          5: 'Unit Exp', 6: 'Unit', 7: 'Report Size', 8: 'Report ID', 9: 'Report Count'}
LOCAL = {0: 'Usage', 1: 'Usage Min', 2: 'Usage Max'}


def walk(start):
    """Parse items from start; stop when the top-level collection closes. Returns (end, lines) or None."""
    i, depth, lines, opened = start, 0, [], False
    while i < len(app) and i < start + 400:
        b = app[i]
        if b == 0xFE:
            return None
        n = (0, 1, 2, 4)[b & 3]
        val = int.from_bytes(app[i + 1:i + 1 + n], 'little')
        kind, tag = (b >> 2) & 3, b >> 4
        table = (MAIN, GLOBAL, LOCAL)[kind] if kind < 3 else {}
        name = table.get(tag)
        if name is None:
            return None
        if kind == 0 and tag == 10:
            depth += 1; opened = True
        if kind == 0 and tag == 12:
            depth -= 1
        lines.append(f"  {i:05X}: {app[i:i+1+n].hex(' '):<15} {'  ' * max(depth - (1 if tag == 10 and kind == 0 else 0), 0)}{name} 0x{val:X}")
        i += 1 + n
        if opened and depth == 0:
            return i, lines
    return None


i = LO
while i < HI:
    if app[i:i + 2] in (b'\x05\x01', b'\x05\x0c', b'\x05\x0d', b'\x06\x00'):
        r = walk(i)
        if r:
            end, lines = r
            print(f'--- descriptor block 0x{i:05X}..0x{end:05X} ({end - i} bytes)')
            print('\n'.join(lines))
            i = end
            continue
    i += 1
