"""Pede ao Terminal do Mac para gravar o corte Keepa que já está na memória."""
import subprocess
import time
from pathlib import Path

PID = 23663
ROOT = Path("/Volumes/HD 1Tb/Vibecoding/Promo Livros")
shutil_src = ROOT / "scripts" / "_dump_found.py"
Path("/tmp/dump_found.py").write_bytes(shutil_src.read_bytes().replace(b"\r\n", b"\n"))
Path("/tmp/lldb_dump.txt").write_text(
    "\n".join(
        [
            f"process attach --pid {PID}",
            "expr -- (int)PyGILState_Ensure()",
            "expr -- (int)PyRun_SimpleString(\"exec(open('/tmp/dump_found.py', encoding='utf-8').read())\")",
            "process detach",
            "quit",
        ]
    )
    + "\n",
    encoding="utf-8",
)
Path("/tmp/run_lldb.sh").write_text(
    "#!/bin/zsh\n"
    "lldb --batch -s /tmp/lldb_dump.txt > /tmp/lldb_gui_out.txt 2>&1\n"
    "echo DONE >> /tmp/lldb_gui_out.txt\n",
    encoding="utf-8",
)
Path("/tmp/run_lldb.sh").chmod(0o755)
Path("/tmp/lldb_gui_out.txt").unlink(missing_ok=True)
Path("/tmp/promo-keepa-dump.txt").unlink(missing_ok=True)
completed = subprocess.run(
    [
        "osascript",
        "-e",
        'tell application "Terminal" to do script "/bin/zsh /tmp/run_lldb.sh"',
    ],
    check=False,
    text=True,
    capture_output=True,
)
print("APPLESCRIPT", completed.returncode)
print(completed.stdout)
print(completed.stderr)
note = Path("/tmp/promo-keepa-dump.txt")
gui = Path("/tmp/lldb_gui_out.txt")
for _ in range(20):
    if note.is_file() or (gui.is_file() and "DONE" in gui.read_text(encoding="utf-8", errors="replace")):
        break
    time.sleep(1)
print("NOTE", note.read_text(encoding="utf-8")[:400] if note.is_file() else "missing")
print("GUI", gui.read_text(encoding="utf-8", errors="replace")[-1500:] if gui.is_file() else "missing")
