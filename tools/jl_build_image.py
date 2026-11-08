"""Build a flash image for the Yiser-J6 (JieLi BD19) from the ORIGINAL image + a new app.bin/cfg_tool.bin.

usage: python jl_build_image.py <original_flash.bin> <chipkey hex> <app.bin> <cfg_tool.bin> <out_flash.bin> [p11_code.bin]

After the app area comes a trailing resource entry (p11_code.bin, the low-power core's code) placed right
after the app area's last byte, unaligned, as the last entry (index=1) - exactly like isd_download does.
If app+p11 would run into the VM, the VM is moved up to the next 4 KB boundary (same end address).

Keeps unchanged: flash header, uboot.boot, isd_config.ini (0x0000-0x1FFF) and everything from 0x3F000 up
(key_mac / BT info). Rebuilds the app area at 0x2000: app_area_head + nested entries (app.bin, cfg_tool.bin,
and the original VM/PRCT/BTIF area descriptors), encrypts it with the chip key, recomputes all CRCs, and
erases the old VM (settings) contents so the new firmware starts clean.
"""
import os, struct, sys, importlib.util

here = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location('u', os.path.join(here, 'jl_unpack.py'))
u = importlib.util.module_from_spec(spec); spec.loader.exec_module(u)

APP = 0x2000            # app area base in flash
KEEP_FROM = 0x3F000     # key_mac and above: never touched
APP_OFF = 0x120         # app.bin offset inside the app area (matches CODE_BEG 0x1E00120)


def fix_hdr(buf, off):
    struct.pack_into('<H', buf, off, u.crc16(bytes(buf[off + 2:off + 32])))


def main():
    src, key_hex, app_path, cfg_path, out = sys.argv[1:6]
    key = int(key_hex, 16)
    fw = bytearray(open(src, 'rb').read())
    app = open(app_path, 'rb').read()
    cfg = open(cfg_path, 'rb').read()
    p11 = open(sys.argv[6], 'rb').read() if len(sys.argv) > 6 else None

    # decrypt original app area to read its directory
    end = len(bytes(fw[:KEEP_FROM]).rstrip(b'\xff'))
    dec = bytearray(fw)
    u.sfc(dec, APP, end - APP, APP, key)
    head = bytearray(dec[APP:APP + 32])
    assert u.parse_entry(bytes(head))['name'] == 'app_area_head'
    nested = []
    o = APP + 32
    while True:
        raw = bytearray(dec[o:o + 32]); e = u.parse_entry(bytes(raw)); assert e['crc_ok']
        nested.append((e, raw)); o += 32
        if e['index']:
            break
    names = [e['name'] for e, _ in nested]
    assert names[:2] == ['app.bin', 'cfg_tool.bin'], names
    vm = next(e for e, _ in nested if e['name'] == 'VM')
    assert APP_OFF == nested[0][0]['off'] and 32 + 32 * len(nested) <= APP_OFF
    gap = bytes(dec[APP + 32 + 32 * len(nested):APP + APP_OFF])     # whatever sits between the directory and app.bin

    cfg_off = APP_OFF + len(app)
    data_end = cfg_off + len(cfg)                     # relative to APP (end of app_area_head's data)

    # trailing resource entry (p11_code.bin) from the original, right after app_area_head's data
    head_e = u.parse_entry(bytes(head))
    tr_off = head_e['size']                           # original position (relative), unaligned
    tr = u.parse_entry(bytes(dec[APP + tr_off:APP + tr_off + 32]))
    assert tr['crc_ok'] and tr['name'] == 'p11_code.bin' and tr['index'] == 1, tr
    tr_hdr = bytearray(dec[APP + tr_off:APP + tr_off + 32])
    if p11 is None:
        p11 = bytes(dec[APP + tr_off + 32:APP + tr_off + tr['size']])
    area_end = data_end + 32 + len(p11)

    # VM / PRCT: move the VM up if needed (keep its end), protect range = everything before the VM
    vm_off, vm_end = vm['off'], vm['off'] + vm['size']
    if area_end > vm_off:
        vm_off = (area_end + 0xFFF) & ~0xFFF
        print(f'moving VM 0x{vm["off"]:X} -> 0x{vm_off:X} (relative), size 0x{vm["size"]:X} -> 0x{vm_end - vm_off:X}')
    assert vm_end - vm_off >= 0x8000, 'VM would get too small'

    # new app area (plaintext), relative to APP
    area = bytearray(b'\xff' * area_end)
    area[0:32] = head
    for i, (e, raw) in enumerate(nested):
        raw = bytearray(raw)
        if e['name'] == 'app.bin':
            struct.pack_into('<HII', raw, 2, u.crc16(app), APP_OFF, len(app))
        elif e['name'] == 'cfg_tool.bin':
            struct.pack_into('<HII', raw, 2, u.crc16(cfg), cfg_off, len(cfg))
        elif e['name'] == 'VM':
            struct.pack_into('<II', raw, 4, vm_off, vm_end - vm_off)
        elif e['name'] == 'PRCT':
            struct.pack_into('<II', raw, 4, 0, vm_off)
        fix_hdr(raw, 0)
        area[32 + 32 * i:64 + 32 * i] = raw
    area[32 + 32 * len(nested):APP_OFF] = gap
    area[APP_OFF:APP_OFF + len(app)] = app
    area[cfg_off:cfg_off + len(cfg)] = cfg
    # app_area_head: size covers through the end of cfg_tool.bin; data CRC over everything after its header
    struct.pack_into('<I', area, 8, data_end)
    struct.pack_into('<H', area, 2, u.crc16(bytes(area[32:data_end])))
    fix_hdr(area, 0)
    # trailing p11_code.bin entry: header (data follows it) + data
    struct.pack_into('<HII', tr_hdr, 2, u.crc16(p11), 32, 32 + len(p11))
    fix_hdr(tr_hdr, 0)
    area[data_end:data_end + 32] = tr_hdr
    area[data_end + 32:area_end] = p11
    assert u.parse_entry(bytes(area[data_end:data_end + 32]))['crc_ok']

    # self-check before encrypting
    chk = u.parse_entry(bytes(area[0:32]))
    assert chk['crc_ok'] and chk['size'] == data_end and chk['off'] == 0x1E00120
    for i in range(len(nested)):
        assert u.parse_entry(bytes(area[32 + 32 * i:64 + 32 * i]))['crc_ok']

    new = bytearray(fw)
    new[APP:KEEP_FROM] = b'\xff' * (KEEP_FROM - APP)          # erase old app area + old VM contents
    enc_area = bytearray(b'\x00' * APP) + area                 # place at its flash address, then encrypt
    u.sfc(enc_area, APP, area_end, APP, key)
    new[APP:APP + area_end] = enc_area[APP:APP + area_end]
    assert new[:APP] == fw[:APP] and new[KEEP_FROM:] == fw[KEEP_FROM:]
    open(out, 'wb').write(new)

    print(f'app.bin {len(app)} B @0x{APP + APP_OFF:05X}, cfg_tool.bin {len(cfg)} B @0x{APP + cfg_off:05X}, '
          f'p11_code.bin {len(p11)} B entry @0x{APP + data_end:05X}, area ends 0x{APP + area_end:05X}, '
          f'VM (erased) 0x{APP + vm_off:05X}-0x{APP + vm_end:05X}')
    print(f'free before VM: {vm_off - area_end} bytes')
    print(f'image written: {out}  (write range 0x{APP:05X}-0x{KEEP_FROM - 1:05X})')


if __name__ == '__main__':
    main()
