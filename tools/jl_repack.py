# AI-written: this script was written by Anthropic's Claude (Claude Code). See README "AI disclosure".
"""Patch the decrypted app.bin inside a JieLi BD19 flash image and rebuild a valid, re-encrypted image.

usage: python jl_repack.py <original_flash.bin> <chipkey hex> <patch.json> <out_flash.bin>
patch.json: {"0x132E4": "hexbytes", ...}   offsets are into app.bin (decrypted)

Recomputes: app.bin data CRC + its entry header CRC, app_area_head data CRC + header CRC.
Prints the 4 KB flash sectors that differ from the original (only those need writing).
"""
import json, struct, sys, importlib.util, os

here = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location('u', os.path.join(here, 'jl_unpack.py'))
u = importlib.util.module_from_spec(spec); spec.loader.exec_module(u)

APP = 0x2000                     # app area (app_dir_head data) in flash


def set_entry_crcs(buf, hdr_off, data_crc=None):
    """Write data CRC (if given) into the 32-byte entry at hdr_off, then fix its header CRC."""
    if data_crc is not None:
        struct.pack_into('<H', buf, hdr_off + 2, data_crc)
    struct.pack_into('<H', buf, hdr_off, u.crc16(bytes(buf[hdr_off + 2:hdr_off + 32])))


def main():
    src, key_hex, patch_path, out = sys.argv[1:5]
    key = int(key_hex, 16)
    fw = bytearray(open(src, 'rb').read())
    end = len(bytes(fw).rstrip(b'\xff'))
    dec = bytearray(fw)
    u.sfc(dec, APP, end - APP, APP, key)

    head = u.parse_entry(bytes(dec[APP:APP + 32]))
    assert head['name'] == 'app_area_head' and head['crc_ok']
    # locate app.bin's nested entry
    sub, app_hdr, app_e = APP + 32, None, None
    while True:
        e = u.parse_entry(bytes(dec[sub:sub + 32]))
        assert e['crc_ok'], 'bad nested entry'
        if e['name'] == 'app.bin':
            app_hdr, app_e = sub, e
        sub += 32
        if e['index']:
            break
    app_start = APP + app_e['off']
    app_len = app_e['size']

    patch = json.load(open(patch_path))
    for off_s, hexdata in patch.items():
        off = int(off_s, 0)
        data = bytes.fromhex(hexdata.replace(' ', ''))
        assert 0 <= off and off + len(data) <= app_len, f'patch at {off_s} outside app.bin'
        old = bytes(dec[app_start + off:app_start + off + len(data)])
        dec[app_start + off:app_start + off + len(data)] = data
        print(f'app.bin+0x{off:05X}: {old.hex(" ")}  ->  {data.hex(" ")}')

    # checksums: app.bin data, its header, then the app_area_head data + header
    set_entry_crcs(dec, app_hdr, u.crc16(bytes(dec[app_start:app_start + app_len])))
    set_entry_crcs(dec, APP, u.crc16(bytes(dec[APP + 32:APP + head['size']])))

    # verify by re-parsing the decrypted image
    assert u.parse_entry(bytes(dec[APP:APP + 32]))['crc_ok']
    e2 = u.parse_entry(bytes(dec[app_hdr:app_hdr + 32]))
    assert e2['crc_ok'] and e2['dcrc'] == u.crc16(bytes(dec[app_start:app_start + app_len]))

    new = bytearray(dec)
    u.sfc(new, APP, end - APP, APP, key)            # re-encrypt
    open(out, 'wb').write(new)

    sectors = sorted({i // 0x1000 * 0x1000 for i in range(len(fw)) if fw[i] != new[i]})
    print(f'wrote {out}; changed 4 KB sectors: {["0x%05X" % s for s in sectors]}')
    for s in sectors:
        open(f'{out}.sector_{s:05X}.bin', 'wb').write(new[s:s + 0x1000])


if __name__ == '__main__':
    main()
