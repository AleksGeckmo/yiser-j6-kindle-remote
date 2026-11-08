# AI-written: this script was written by Anthropic's Claude (Claude Code). See README "AI disclosure".
"""Read-only: list what each HID collection of a paired Yiser-J6 (VID 05AC PID 0220) can report, via Windows hid.dll."""
import ctypes, subprocess, json
from ctypes import wintypes as w

hid = ctypes.WinDLL("hid.dll")
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.CreateFileW.restype = w.HANDLE
k32.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, w.LPVOID, w.DWORD, w.DWORD, w.HANDLE]
INVALID = w.HANDLE(-1).value
HIDP_INPUT, HIDP_OUTPUT, HIDP_FEATURE = 0, 1, 2


class CAPS(ctypes.Structure):
    _fields_ = [("Usage", w.USHORT), ("UsagePage", w.USHORT), ("InLen", w.USHORT), ("OutLen", w.USHORT),
                ("FeatLen", w.USHORT), ("Reserved", w.USHORT * 17), ("NLink", w.USHORT),
                ("NInBtn", w.USHORT), ("NInVal", w.USHORT), ("NInIdx", w.USHORT),
                ("NOutBtn", w.USHORT), ("NOutVal", w.USHORT), ("NOutIdx", w.USHORT),
                ("NFeatBtn", w.USHORT), ("NFeatVal", w.USHORT), ("NFeatIdx", w.USHORT)]


class BTN(ctypes.Structure):
    _fields_ = [("UsagePage", w.USHORT), ("ReportID", ctypes.c_ubyte), ("IsAlias", ctypes.c_ubyte),
                ("BitField", w.USHORT), ("LinkCollection", w.USHORT), ("LinkUsage", w.USHORT),
                ("LinkUsagePage", w.USHORT), ("IsRange", ctypes.c_ubyte), ("IsStringRange", ctypes.c_ubyte),
                ("IsDesignatorRange", ctypes.c_ubyte), ("IsAbsolute", ctypes.c_ubyte),
                ("ReportCount", w.USHORT), ("Reserved2", w.USHORT), ("Reserved", w.ULONG * 9),
                ("UsageMin", w.USHORT), ("UsageMax", w.USHORT), ("u", w.USHORT * 6)]


class VAL(ctypes.Structure):
    _fields_ = [("UsagePage", w.USHORT), ("ReportID", ctypes.c_ubyte), ("IsAlias", ctypes.c_ubyte),
                ("BitField", w.USHORT), ("LinkCollection", w.USHORT), ("LinkUsage", w.USHORT),
                ("LinkUsagePage", w.USHORT), ("IsRange", ctypes.c_ubyte), ("IsStringRange", ctypes.c_ubyte),
                ("IsDesignatorRange", ctypes.c_ubyte), ("IsAbsolute", ctypes.c_ubyte), ("HasNull", ctypes.c_ubyte),
                ("Reserved", ctypes.c_ubyte), ("BitSize", w.USHORT), ("ReportCount", w.USHORT),
                ("Reserved2", w.USHORT * 5), ("UnitsExp", w.ULONG), ("Units", w.ULONG),
                ("LogicalMin", ctypes.c_long), ("LogicalMax", ctypes.c_long),
                ("PhysicalMin", ctypes.c_long), ("PhysicalMax", ctypes.c_long),
                ("UsageMin", w.USHORT), ("UsageMax", w.USHORT), ("u", w.USHORT * 6)]


assert ctypes.sizeof(BTN) == 72 and ctypes.sizeof(VAL) == 72, (ctypes.sizeof(BTN), ctypes.sizeof(VAL))

ids = subprocess.run(["powershell", "-NoProfile", "-Command",
                      "Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -match 'VID&0205AC_PID&0220.*&COL' } | "
                      "Select-Object -ExpandProperty InstanceId"], capture_output=True, text=True).stdout.split()
for iid in sorted(ids):
    path = "\\\\?\\" + iid.replace("\\", "#") + "#{4d1e55b2-f16f-11cf-88cb-001111000030}"
    h = k32.CreateFileW(path, 0, 3, None, 3, 0, None)
    print("=" * 70)
    print(iid.split("_REV")[1][-6:] if "&COL" in iid else iid)
    if h == INVALID or h is None:
        print("  could not open:", ctypes.get_last_error())
        continue
    pp = ctypes.c_void_p()
    if not hid.HidD_GetPreparsedData(w.HANDLE(h), ctypes.byref(pp)):
        print("  no preparsed data")
        k32.CloseHandle(w.HANDLE(h))
        continue
    caps = CAPS()
    hid.HidP_GetCaps(pp, ctypes.byref(caps))
    print(f"  top usage page 0x{caps.UsagePage:02X} usage 0x{caps.Usage:02X}  input report {caps.InLen} B, output {caps.OutLen} B")
    for kind, n in ((HIDP_INPUT, caps.NInBtn), (HIDP_OUTPUT, caps.NOutBtn)):
        if n:
            arr = (BTN * n)(); cnt = w.USHORT(n)
            hid.HidP_GetButtonCaps(kind, arr, ctypes.byref(cnt), pp)
            for b in arr[:cnt.value]:
                rng = f"0x{b.UsageMin:02X}-0x{b.UsageMax:02X}" if b.IsRange else f"0x{b.UsageMin:02X}"
                print(f"  {'IN ' if kind == 0 else 'OUT'} buttons: report id {b.ReportID}, page 0x{b.UsagePage:02X}, usages {rng}, count {b.ReportCount}")
    for kind, n in ((HIDP_INPUT, caps.NInVal), (HIDP_OUTPUT, caps.NOutVal)):
        if n:
            arr = (VAL * n)(); cnt = w.USHORT(n)
            hid.HidP_GetValueCaps(kind, arr, ctypes.byref(cnt), pp)
            for v in arr[:cnt.value]:
                rng = f"0x{v.UsageMin:02X}-0x{v.UsageMax:02X}" if v.IsRange else f"0x{v.UsageMin:02X}"
                print(f"  {'IN ' if kind == 0 else 'OUT'} value: report id {v.ReportID}, page 0x{v.UsagePage:02X}, usage {rng}, "
                      f"{v.BitSize} bits x{v.ReportCount}, logical {v.LogicalMin}..{v.LogicalMax}, abs={v.IsAbsolute}")
    hid.HidD_FreePreparsedData(pp)
    k32.CloseHandle(w.HANDLE(h))
