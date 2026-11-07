#!/usr/bin/env python3
"""Resume a CourtListener opinions CSV from mid-stream: emit the header line,
drop everything up to the first line that is unmistakably a record start,
then pass the rest through unchanged.

A record starts with a quoted integer id and two quoted timestamps:
    "7090799","2022-07-24 12:05:34.084035+00","2025-06-06 18:30:39.451266+00",
Opinion text is quoted and multi-line, so an arbitrary line can be inside a
field; two consecutive quoted timestamps at the start of a line do not occur
in opinion text, so matching that at a line start resyncs the CSV parser.

    usage: ... | lbzip2 -dc | csv_resync.py --header 'id,date_created,...' | build-text --stdin
"""
import re
import sys

START = re.compile(rb'^"\d+","\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[^"\n]*","\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[^"\n]*",', re.M)


def main():
    header = sys.argv[sys.argv.index("--header") + 1].encode()
    inp, out = sys.stdin.buffer, sys.stdout.buffer
    out.write(header.rstrip(b"\n") + b"\n")
    buf = b""
    dropped = 0
    while True:
        c = inp.read(1 << 20)
        if not c:
            print("csv_resync: no record start found", file=sys.stderr); sys.exit(2)
        buf += c
        m = START.search(buf, 1)          # pos 1: a match at 0 could be a torn line
        if m:
            dropped += m.start()
            out.write(buf[m.start():])
            break
        keep = 4096                       # enough to hold a straddling record start
        dropped += len(buf) - keep
        buf = buf[-keep:]
    print(f"csv_resync: dropped {dropped} bytes before first record", file=sys.stderr, flush=True)
    while True:
        c = inp.read(1 << 20)
        if not c:
            break
        out.write(c)
    out.flush()


if __name__ == "__main__":
    main()
