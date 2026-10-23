"""Show Blaze log traffic since the last mark, without the ticker/census spam.
usage: python -I blazetail.py mark            remember the current end of server/logs/blaze_server.log
       python -I blazetail.py show [--full]   print requests/replies since the mark (--full: decoded bodies too)"""
import re
import sys
from pathlib import Path

LOG = Path(r"C:\madden20_online\server\logs\blaze_server.log")
MARK = Path(r"C:\madden20_online\runs\blazetail.mark")
SPAM = re.compile(r"0x8d6/0x3|CensusData|AssociationLists|Util\.Ping|comp=0x0000 cmd=0x0000")

if sys.argv[1] == "mark":
    MARK.write_text(str(LOG.stat().st_size))
    sys.exit()
start = int(MARK.read_text()) if MARK.exists() else 0
with open(LOG, "rb") as f:
    f.seek(start)
    text = f.read().decode("utf-8", "replace")
full = "--full" in sys.argv
skip_body = False
for line in text.splitlines():
    head = re.match(r"^\d\d:\d\d:\d\d ", line)
    if head:
        skip_body = bool(SPAM.search(line))
        if not skip_body:
            print(line[:200])
    elif full and not skip_body:
        print(line[:200])
