"""Print TID (hex) -> thread description for a process. usage: python thread_names.py <pid>"""
import ctypes
import ctypes.wintypes as wt
import sys

k = ctypes.windll.kernel32
pid = int(sys.argv[1])


class TE32(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ThreadID", wt.DWORD),
                ("th32OwnerProcessID", wt.DWORD), ("tpBasePri", ctypes.c_long),
                ("tpDeltaPri", ctypes.c_long), ("dwFlags", wt.DWORD)]


k.GetThreadDescription.argtypes = [wt.HANDLE, ctypes.POINTER(ctypes.c_wchar_p)]
snap = k.CreateToolhelp32Snapshot(0x4, 0)
te = TE32()
te.dwSize = ctypes.sizeof(TE32)
ok = k.Thread32First(snap, ctypes.byref(te))
while ok:
    if te.th32OwnerProcessID == pid:
        h = k.OpenThread(0x0800 | 0x0040, False, te.th32ThreadID)  # QUERY_LIMITED | QUERY
        name = ctypes.c_wchar_p()
        desc = ""
        if h and k.GetThreadDescription(h, ctypes.byref(name)) >= 0 and name.value:
            desc = name.value
        if h:
            k.CloseHandle(h)
        print(f"{te.th32ThreadID:x}\t{desc}")
    ok = k.Thread32Next(snap, ctypes.byref(te))
