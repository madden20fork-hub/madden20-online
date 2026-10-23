"""Per-thread CPU usage of the running shadps4 process over an interval, with thread names
(GetThreadDescription: shadPS4 names host threads, guest threads carry the PS4 thread name).
usage: python -I threadcpu.py [seconds] [top]"""
import ctypes
import ctypes.wintypes as wt
import subprocess
import sys
import time

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
TH32CS_SNAPTHREAD = 0x4


class THREADENTRY32(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ThreadID", wt.DWORD),
                ("th32OwnerProcessID", wt.DWORD), ("tpBasePri", ctypes.c_long), ("tpDeltaPri", ctypes.c_long),
                ("dwFlags", wt.DWORD)]


k32.OpenThread.restype = wt.HANDLE
k32.CreateToolhelp32Snapshot.restype = wt.HANDLE


def pid_of():
    out = subprocess.run('tasklist /FI "IMAGENAME eq shadps4.exe" /FO CSV /NH', capture_output=True, text=True,
                         shell=True).stdout
    return int(out.split('","')[1])


def threads(pid):
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    te = THREADENTRY32()
    te.dwSize = ctypes.sizeof(te)
    ok = k32.Thread32First(snap, ctypes.byref(te))
    tids = []
    while ok:
        if te.th32OwnerProcessID == pid:
            tids.append(te.th32ThreadID)
        ok = k32.Thread32Next(snap, ctypes.byref(te))
    k32.CloseHandle(snap)
    return tids


def cpu_and_name(tid):
    h = k32.OpenThread(0x1800 | 0x0040, False, tid)  # QUERY_LIMITED_INFORMATION | QUERY_INFORMATION
    if not h:
        return None, ""
    c, e, kt, ut = wt.FILETIME(), wt.FILETIME(), wt.FILETIME(), wt.FILETIME()
    k32.GetThreadTimes(h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(kt), ctypes.byref(ut))
    t = ((kt.dwHighDateTime << 32 | kt.dwLowDateTime) + (ut.dwHighDateTime << 32 | ut.dwLowDateTime)) / 1e7
    kern = (kt.dwHighDateTime << 32 | kt.dwLowDateTime) / 1e7
    name = ctypes.c_wchar_p()
    try:
        k32.GetThreadDescription(h, ctypes.byref(name))
        nm = name.value or ""
    except Exception:  # noqa: BLE001
        nm = ""
    k32.CloseHandle(h)
    return (t, kern), nm


def main():
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 5
    top = int(sys.argv[2]) if len(sys.argv) > 2 else 15
    pid = pid_of()
    a = {t: cpu_and_name(t) for t in threads(pid)}
    time.sleep(secs)
    rows = []
    for t in threads(pid):
        (cur, nm) = cpu_and_name(t)
        if cur is None or t not in a or a[t][0] is None:
            continue
        d = cur[0] - a[t][0][0]
        dk = cur[1] - a[t][0][1]
        rows.append((d / secs * 100, dk / secs * 100, t, nm))
    rows.sort(reverse=True)
    total = sum(r[0] for r in rows)
    print(f"pid {pid}: {len(rows)} threads, total {total:.0f}% of one core over {secs}s")
    for pct, kpct, t, nm in rows[:top]:
        print(f"  {pct:6.1f}%  (kernel {kpct:5.1f}%)  tid {t:6d}  {nm}")


main()
