from pathlib import Path

assert Path("hello.txt").read_text() == "hello tinyagent\n"
