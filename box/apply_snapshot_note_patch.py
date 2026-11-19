#!/usr/bin/env python3
"""apply_snapshot_note_patch.py - when the nationwide index has no case at a citation AND the draft dates it in or after the
snapshot's year, say so: the index is a quarterly snapshot, a recent decision may simply be newer than it.
Usage: apply_snapshot_note_patch.py /opt/banksy/lex/cite_check.py   (keeps .bak-snapnote)"""
import sys, shutil
path = sys.argv[1]; s = open(path, encoding="utf-8").read()
if "newer than that snapshot" in s: print("already patched"); sys.exit(0)
old = '''            notes.append("%s has no case at this citation either. That index has gaps (unpublished and some state decisions) - confirm in Westlaw or Lexis before relying on it or striking it" % src)'''
new = old + '''
            y = str(c.get("year") or "")
            if y.isdigit() and snap[:4].isdigit() and int(y) >= int(snap[:4]):
                notes.append("the draft dates this case %s, and the nationwide index is a snapshot from %s: a decision newer than that snapshot would not be in it yet" % (y, snap))'''
if s.count(old) != 1: print("ANCHOR matched %d times - nothing written" % s.count(old)); sys.exit(2)
shutil.copy2(path, path + ".bak-snapnote"); open(path, "w", encoding="utf-8").write(s.replace(old, new)); print("patched; backup at %s.bak-snapnote" % path)
