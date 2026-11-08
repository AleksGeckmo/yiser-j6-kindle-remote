# AI-written: this script was written by Anthropic's Claude (Claude Code). See README "AI disclosure".
"""Raw Input logger for the Yiser-J6 Bluetooth remote (or any HID device).

No dependencies. Logs mouse, keyboard and HID (digitizer/consumer) events with
the source device path so remote events can be told apart from your real mouse.
Run:  python remote_logger.py     (Ctrl+C to stop)
Output also goes to remote_log.txt next to this script.
"""
import ctypes, struct, sys, time, os
from ctypes import wintypes as w

u32 = ctypes.windll.user32
k32 = ctypes.windll.kernel32
LRESULT = ctypes.c_ssize_t
u32.DefWindowProcW.restype = LRESULT
u32.DefWindowProcW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
u32.GetRawInputData.argtypes = [w.HANDLE, w.UINT, ctypes.c_void_p, ctypes.POINTER(w.UINT), w.UINT]
u32.GetRawInputData.restype = w.UINT
u32.GetRawInputDeviceInfoW.argtypes = [w.HANDLE, w.UINT, ctypes.c_void_p, ctypes.POINTER(w.UINT)]
u32.GetRawInputDeviceInfoW.restype = w.UINT
u32.CreateWindowExW.restype = w.HWND
u32.CreateWindowExW.argtypes = [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, w.HWND, w.HMENU, w.HINSTANCE, w.LPVOID]

WM_INPUT = 0x00FF
RIM_MOUSE, RIM_KEYBOARD, RIM_HID = 0, 1, 2
RIDEV_INPUTSINK, RIDEV_PAGEONLY = 0x100, 0x20
HWND_MESSAGE = w.HWND(-3)

MOUSE_BTN = {0x1: "L down", 0x2: "L up", 0x4: "R down", 0x8: "R up", 0x10: "M down", 0x20: "M up",
             0x40: "B4 down", 0x80: "B4 up", 0x100: "B5 down", 0x200: "B5 up",
             0x400: "WHEEL", 0x800: "HWHEEL"}


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [("usUsagePage", w.USHORT), ("usUsage", w.USHORT),
                ("dwFlags", w.DWORD), ("hwndTarget", w.HWND)]


class MSG(ctypes.Structure):
    _fields_ = [("hwnd", w.HWND), ("message", w.UINT), ("wParam", w.WPARAM), ("lParam", w.LPARAM),
                ("time", w.DWORD), ("pt", w.POINT)]


logf = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "remote_log.txt"), "a", encoding="utf-8")
t0 = time.time()
names = {}


def log(s):
    line = f"[{time.time() - t0:8.3f}] {s}"
    print(line, flush=True)
    logf.write(line + "\n")
    logf.flush()


def dev_name(h):
    if h in names:
        return names[h]
    size = w.UINT(0)
    u32.GetRawInputDeviceInfoW(h, 0x20000007, None, ctypes.byref(size))
    buf = ctypes.create_unicode_buffer(size.value + 1)
    u32.GetRawInputDeviceInfoW(h, 0x20000007, buf, ctypes.byref(size))
    n = buf.value or "?"
    names[h] = n
    log(f"new device {hex(h or 0)}: {n}")
    return n


def short(h):
    n = dev_name(h)
    # e.g. \\?\HID#VID_xxxx&PID_xxxx#... -> VID/PID
    import re
    # Bluetooth HID names look like VID&0205ac_PID&0220 (02 = BT vendor-id source, VID is 05ac)
    m = re.search(r"VID&02([0-9A-Fa-f]{4}).*?PID&([0-9A-Fa-f]{4})", n) or \
        re.search(r"VID_([0-9A-Fa-f]{4}).*?PID_([0-9A-Fa-f]{4})", n)
    return f"VID:{m.group(1)} PID:{m.group(2)}" if m else n[:40]


def handle(lparam):
    size = w.UINT(0)
    u32.GetRawInputData(lparam, 0x10000003, None, ctypes.byref(size), 24)
    buf = ctypes.create_string_buffer(size.value)
    u32.GetRawInputData(lparam, 0x10000003, buf, ctypes.byref(size), 24)
    raw = buf.raw
    dtype, dsize, hdev, _ = struct.unpack_from("<IIQQ", raw, 0)
    d = raw[24:]
    tag = short(hdev)
    if dtype == RIM_MOUSE:
        flags, _, bflags, bdata, rawb, x, y, extra = struct.unpack_from("<HHHHLllL", d, 0)
        btn = ",".join(v for k, v in MOUSE_BTN.items() if bflags & k)
        mode = "ABS" if flags & 1 else "REL"
        if flags & 1 == 0 and x == 0 and y == 0 and not bflags:
            return
        log(f"MOUSE  {tag}  {mode} x={x} y={y}  btn=[{btn}] data={bdata}")
    elif dtype == RIM_KEYBOARD:
        make, kflags, _, vkey, msg, extra = struct.unpack_from("<HHHHLL", d, 0)
        log(f"KEY    {tag}  vk=0x{vkey:02X} make=0x{make:02X} {'UP' if kflags & 1 else 'DOWN'}")
    else:
        szhid, count = struct.unpack_from("<II", d, 0)
        for i in range(count):
            rep = d[8 + i * szhid: 8 + (i + 1) * szhid]
            log(f"HID    {tag}  report({len(rep)}B) = {rep.hex(' ')}")


def main():
    hwnd = u32.CreateWindowExW(0, "STATIC", "rawlog", 0, 0, 0, 0, 0, HWND_MESSAGE, None, None, None)
    if not hwnd:
        sys.exit("window creation failed")
    # (usage page, usage): mouse, keyboard, touch screen, pen, touchpad, consumer control
    wanted = [(1, 2), (1, 6), (0x0D, 4), (0x0D, 2), (0x0D, 5), (0x0C, 1)]
    arr = (RAWINPUTDEVICE * len(wanted))(*[RAWINPUTDEVICE(p, u, RIDEV_INPUTSINK, hwnd) for p, u in wanted])
    if not u32.RegisterRawInputDevices(arr, len(wanted), ctypes.sizeof(RAWINPUTDEVICE)):
        sys.exit(f"RegisterRawInputDevices failed: {k32.GetLastError()}")
    log("listening - press buttons on the remote (Ctrl+C to stop)")
    msg = MSG()
    while True:
        r = u32.GetMessageW(ctypes.byref(msg), None, 0, 0)
        if r <= 0:
            break
        if msg.message == WM_INPUT:
            try:
                handle(msg.lParam)
            except Exception as e:
                log(f"parse error: {e}")
        u32.DispatchMessageW(ctypes.byref(msg))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
