#!/usr/bin/env python3
"""Turn the TAIL of a .bz2 file (bytes from an arbitrary offset, e.g. from
`curl -r OFFSET-`) into a valid standalone .bz2 stream on stdout.

bzip2 blocks are independent but NOT byte-aligned: each starts with the
48-bit magic 0x314159265359 at any bit offset, followed by the block's
32-bit CRC.  The stream ends with 0x177245385090 + a combined CRC over all
blocks.  So we: find the first block magic (any bit offset), emit a stream
header, emit the bits from there, shifted to byte alignment, track every
block CRC we pass, and when we reach the original end-of-stream marker
replace it with one whose combined CRC covers only the blocks we emitted.
The result decompresses with any bzip2 and passes its CRC checks.

    usage: curl -r OFFSET- URL | bz2_resume.py [--level 9] | lbzip2 -dc
"""
import sys

BLOCK = 0x314159265359
EOS = 0x177245385090
CHUNK = 1 << 20


def _find_magic(buf: bytes, magic: int, start_bit: int = 0):
    """Yield bit offsets (into buf) of `magic` (48 bits) at any alignment.
    For alignment a in 0..7 the 5 middle bytes are fully determined, so
    bytes.find does the heavy lifting at C speed; byte 0 and 6 are masked."""
    m = magic.to_bytes(6, "big")
    for a in range(8):
        if a == 0:
            pat, lead = m, 0
        else:
            v = (magic << (8 - a))             # magic shifted right by a bits within 7 bytes
            pat = v.to_bytes(7, "big")[1:6]    # bytes 1..5 are exact
            lead = 1
        i = buf.find(pat, max(0, (start_bit // 8) - lead))
        while i != -1:
            b0 = i - lead                      # byte index where the 7(or 6)-byte window starts
            if b0 >= 0:
                n = 7 if a else 6
                if b0 + n <= len(buf):
                    win = int.from_bytes(buf[b0:b0 + n], "big")
                    val = (win >> (8 * n - 48 - a)) & ((1 << 48) - 1)
                    if val == magic and b0 * 8 + a >= start_bit:
                        yield b0 * 8 + a
            i = buf.find(pat, i + 1)


def main():
    level = "9"
    if "--level" in sys.argv:
        level = sys.argv[sys.argv.index("--level") + 1]
    inp, out = sys.stdin.buffer, sys.stdout.buffer
    err = sys.stderr

    # ---- phase 1: find the first block magic ------------------------------
    buf = b""
    first = None
    while first is None:
        c = inp.read(CHUNK)
        if not c:
            print("bz2_resume: no block magic found in input", file=err); sys.exit(2)
        buf += c
        hits = sorted(_find_magic(buf, BLOCK))
        if hits:
            first = hits[0]
        elif len(buf) > 8 << 20:
            print("bz2_resume: no block magic in first 8 MB", file=err); sys.exit(2)
    k = first % 8
    buf = buf[first // 8:]                     # drop whole bytes before the block
    print(f"bz2_resume: first block at bit {first} (shift {k})", file=err, flush=True)

    out.write(b"BZh" + level.encode())

    # ---- phase 2: stream, shifted by k bits, tracking block CRCs -----------
    # acc/nbits hold not-yet-emitted bits; we always keep a 16-byte tail
    # unemitted so a magic straddling a chunk boundary is still found whole.
    combined = 0
    blocks = 0
    abs_bit = 0          # absolute bit position of buf[0] within the (dropped-prefix) stream
    seen_upto = 0        # magics with abs position < seen_upto were already counted
    acc = 0; nbits = 0
    pending = buf        # bytes not yet pushed into acc
    done = False
    TAIL = 16

    def push(bs: bytes):
        nonlocal acc, nbits
        if bs:
            acc = (acc << (8 * len(bs))) | int.from_bytes(bs, "big")
            nbits += 8 * len(bs)

    def emit_all_but(keep_bits: int):
        nonlocal acc, nbits
        n = (nbits - keep_bits) // 8
        if n > 0:
            out.write((acc >> (nbits - 8 * n)).to_bytes(n, "big"))
            nbits -= 8 * n
            acc &= (1 << nbits) - 1

    # drop the first k bits so the block magic starts byte-aligned in output
    pending_shift = k

    while not done:
        # scan this buffer for block magics and the end-of-stream magic
        for pos in sorted(_find_magic(pending, BLOCK)):
            ab = abs_bit + pos
            if ab < seen_upto:
                continue
            crc_bits_end = pos + 48 + 32
            if crc_bits_end > len(pending) * 8:
                break                        # CRC straddles; next round (tail kept)
            end_byte = (crc_bits_end + 7) // 8
            crc = (int.from_bytes(pending[(pos + 48) // 8:end_byte], "big")
                   >> (end_byte * 8 - crc_bits_end)) & 0xFFFFFFFF
            combined = (((combined << 1) | (combined >> 31)) ^ crc) & 0xFFFFFFFF
            blocks += 1
            seen_upto = ab + 48
        eos = [p for p in _find_magic(pending, EOS) if abs_bit + p >= seen_upto - 48]
        if eos:
            cut = eos[0]                     # bit offset in pending where the original EOS starts
            push(pending[:(cut + 7) // 8])
            # trim to exactly `cut` bits: we pushed ceil(cut/8) bytes
            extra = ((cut + 7) // 8) * 8 - cut
            if pending_shift:
                nbits -= pending_shift; acc &= (1 << nbits) - 1; pending_shift = 0
            nbits -= extra; acc >>= extra
            # append our own trailer: EOS magic + combined CRC, then pad to a byte
            acc = (acc << 48) | EOS; nbits += 48
            acc = (acc << 32) | combined; nbits += 32
            pad = (-nbits) % 8
            acc <<= pad; nbits += pad
            out.write(acc.to_bytes(nbits // 8, "big"))
            done = True
            break
        # no EOS here: push everything except a tail (kept for straddling magics)
        if len(pending) > TAIL:
            push(pending[:-TAIL])
            if pending_shift:
                nbits -= pending_shift; acc &= (1 << nbits) - 1; pending_shift = 0
            emit_all_but(0)
            abs_bit += 8 * (len(pending) - TAIL)
            pending = pending[-TAIL:]
        c = inp.read(CHUNK)
        if not c:
            print("bz2_resume: input ended without an end-of-stream marker", file=err)
            sys.exit(3)
        pending += c
    out.flush()
    print(f"bz2_resume: emitted {blocks} blocks, combined CRC {combined:08x}", file=err)


if __name__ == "__main__":
    main()
