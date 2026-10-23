"""Break the running shadps4 into its attached debugger (DebugBreakProcess). usage: python -I break_in.py"""
import ctypes, sys
sys.path.insert(0, r"C:\madden20_online\tools")
from memscan import pid_of
k = ctypes.windll.kernel32
h = k.OpenProcess(0x1F0FFF, False, pid_of())
print("DebugBreakProcess", k.DebugBreakProcess(h))
