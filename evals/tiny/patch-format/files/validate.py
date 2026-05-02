from pathlib import Path

assert Path("notes.txt").read_text() == "status: done\n"
