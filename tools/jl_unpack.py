# AI-written: this script was written by Anthropic's Claude (Claude Code). See README "AI disclosure".
"""Unpack a JieLi "new firmware" (JLFS) flash image. Reimplemented from kagaimiq's docs/notes.

usage: python jl_unpack.py <flash.bin> <chipkey hex> <outdir>
"""
import os, struct, sys
import crcmod

crc16 = crcmod.mkCrcFun(0x11021, initCrc=0x0000, rev=False)


def enc(buf, off, size, key=0xFFFF):
    """JieLi ENC cipher (XOR with a CRC-16 LFSR keystream)."""
    for i in range(size):
        buf[off + i] ^= key & 0xFF
        key = ((key << 1) ^ (0x1021 if key & 0x8000 else 0)) & 0xFFFF
    return key


def sfc(buf, off, size, base, key, block=32):
    """Address-dependent ENC used for the SFC (memory-mapped) area: key ^ ((addr-base) >> 2) per 32-byte block."""
    i = 0
    while i < size:
        n = min(block - ((off + i - base) % block), size - i)
        a = off + i
        blk_start = a - ((a - base) % block)
        k = key ^ (((blk_start - base) >> 2) & 0xFFFF)
        # run the keystream from the start of the block up to this byte
        tmp = bytearray(block)
        enc(tmp, 0, block, k)
        s = a - blk_start
        for j in range(n):
            buf[a + j] ^= tmp[s + j]
        i += n


ENTRY = struct.Struct('<HHIIBBH16s')


def parse_entry(raw32):
    hcrc, dcrc, off, size, flags, resvd, index, name = ENTRY.unpack(raw32)
    ok = crc16(raw32[2:]) == hcrc
    return dict(hcrc=hcrc, dcrc=dcrc, off=off, size=size, flags=flags, index=index,
                name=''.join(chr(c) if 32 <= c < 127 else '?' for c in name.split(b'\0')[0]), crc_ok=ok)


def main():
    path, key_hex, outdir = sys.argv[1], sys.argv[2], sys.argv[3]
    key = int(key_hex, 16)
    fw = bytearray(open(path, 'rb').read())
    os.makedirs(outdir, exist_ok=True)

    # --- flash header ---
    base = None
    for probe in (0x0, 0x1000, 0x10000):
        h = bytearray(fw[probe:probe + 32])
        enc(h, 0, 32, 0xFFFF)
        if struct.unpack_from('<H', h)[0] and crc16(bytes(h[2:])) == struct.unpack_from('<H', h)[0]:
            base = probe
            break
    if base is None:
        sys.exit('flash header not found')
    h[4:8] = fw[base + 4:base + 8]
    h[16:32] = fw[base + 16:base + 32]
    hcrc, burner, vid, fsize, fsver, align, resvd, spec, pid = struct.unpack('<HH4sIBBBB16s', h)
    print(f'flash header @0x{base:X}: vid={vid!r} flash_size=0x{fsize:X} fs_ver={fsver} '
          f'align={align} special=0x{spec:02X} pid={pid.split(b"\\xff")[0].split(b"\\0")[0]!r}')

    # --- top-level entries, each 32 bytes decrypted independently with key 0xFFFF ---
    print('\ntop-level entries:')
    off = base + 32
    app_base = None
    while True:
        raw = bytearray(fw[off:off + 32])
        enc(raw, 0, 32, 0xFFFF)
        e = parse_entry(bytes(raw))
        data_at = base + e['off']
        print(f"  @0x{off:05X} {e['name']:<16} flags=0x{e['flags']:02X} data@0x{data_at:05X} "
              f"size=0x{e['size']:X} idx={e['index']} crc={'ok' if e['crc_ok'] else 'BAD'}")
        if not e['crc_ok']:
            break
        if e['flags'] == 0x81 and app_base is None:
            app_base = data_at
        elif not (e['flags'] & 0x10) and e['size'] != 0xFFFFFFFF:
            open(os.path.join(outdir, 'top_' + e['name']), 'wb').write(fw[data_at:data_at + e['size']])
        off += 32
        if e['index']:
            break

    if app_base is None:
        sys.exit('no app_dir_head')

    # --- app (SFC) area: decrypt everything from app_base with the chip key ---
    end = len(bytes(fw).rstrip(b'\xff'))
    dec = bytearray(fw)
    sfc(dec, app_base, end - app_base, app_base, key)
    open(os.path.join(outdir, 'app_area_decrypted.bin'), 'wb').write(dec[app_base:end])
    print(f'\napp area @0x{app_base:X}..0x{end:X} decrypted with chip key 0x{key:04X}')

    print('app-area entries (header followed by data):')
    off = app_base
    for _ in range(64):
        e = parse_entry(bytes(dec[off:off + 32]))
        print(f"  @0x{off:05X} {e['name']:<16} flags=0x{e['flags']:02X} off=0x{e['off']:X} "
              f"size=0x{e['size']:X} idx={e['index']} crc={'ok' if e['crc_ok'] else 'BAD'}")
        if not e['crc_ok']:
            break
        if e['name'] and e['size'] != 0xFFFFFFFF:
            data = dec[off + 32:off + e['size']]
            open(os.path.join(outdir, 'app_' + e['name'].replace('/', '_')), 'wb').write(data)
            # nested entries inside app_area_head (no key)
            if off == app_base:
                sub = off + 32
                for _ in range(32):
                    se = parse_entry(bytes(dec[sub:sub + 32]))
                    if not se['crc_ok']:
                        break
                    sdata = dec[off + se['off']:off + se['off'] + se['size']]
                    print(f"      - {se['name']:<16} flags=0x{se['flags']:02X} off=0x{se['off']:X} "
                          f"size=0x{se['size']:X} idx={se['index']}")
                    if se['size'] != 0xFFFFFFFF and not (se['flags'] & 0x10):
                        open(os.path.join(outdir, 'app_' + se['name']), 'wb').write(sdata)
                    sub += 32
                    if se['index']:
                        break
        if e['index'] or e['size'] in (0, 0xFFFFFFFF):
            break
        off += e['size']
        # the next entry (e.g. the trailing p11_code.bin) may follow unaligned; else try 32-byte alignment
        if not parse_entry(bytes(dec[off:off + 32]))['crc_ok']:
            off = (off + 31) & ~31


if __name__ == '__main__':
    main()
