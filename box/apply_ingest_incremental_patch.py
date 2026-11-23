#!/usr/bin/env python3
"""lex_ingest.py: ask CourtListener only for records that changed since the last complete run.

Before: every day each court re-read its whole look-back window (7 to 45 days of decisions, 20 per request), so busy
courts spent most of the free daily allowance re-downloading opinions already on the box.
After:  when a court finished cleanly within the last 6 days, the request adds date_modified >= (that day - 1), so only
new or changed records come back; the decision-date floor widens to 60 days so late-posted decisions are still caught.
Safety: Sundays run the old full window; a forced --since runs the old full window; if CourtListener rejects the
filter (HTTP 400) the run falls back to the full window on the spot and stays there (state key inc_off).
Usage: apply_ingest_incremental_patch.py [path-to-lex_ingest.py]"""
import sys, shutil
p = sys.argv[1] if len(sys.argv) > 1 else "/opt/banksy/lex/lex_ingest.py"; s = open(p, encoding="utf-8").read()
if "incremental_since" in s: print("already patched"); raise SystemExit
def sub(a, b):
    global s
    assert s.count(a) == 1, a[:60]; s = s.replace(a, b)

sub('''# ---------------- fetch ----------------
def fetch(''', '''def incremental_since(cs, override, st):
    """ISO timestamp to pass as date_modified__gte, or None for the full look-back window."""
    if override or st.d.get("inc_off") or dt.date.today().weekday() == 6: return None      # Sunday = full sweep
    try: last = dt.date.fromisoformat(cs.get("last_done") or "")
    except ValueError: return None
    if (dt.date.today() - last).days > 6: return None
    return (last - dt.timedelta(days=1)).isoformat() + "T00:00:00Z"

def first_url(court, kind, path, fields, order, since, inc, page_size):
    floor = (dt.date.today() - dt.timedelta(days=60)).isoformat() if inc else since
    q = ({"docket__court": court, "date_filed__gte": floor} if kind == "clusters"
         else {"cluster__docket__court": court, "cluster__date_filed__gte": floor})
    if inc: q["date_modified__gte"] = inc
    q.update({"order_by": order, "page_size": str(page_size), "fields": fields})
    return CL + path + "?" + urllib.parse.urlencode(q)

# ---------------- fetch ----------------
def fetch(''')
sub('''        log(f"[{court}] since {since}  (budget left {cl.budget_left()})")''',
    '''        if not (cs.get("clusters_next") or cs.get("opinions_next")):       # decided when a window opens; a resumed window keeps what it started with
            cs["inc"] = incremental_since(cs, since_override, st)
        inc = cs.get("inc"); st.save()
        log(f"[{court}] " + (f"changed since {inc[:10]}" if inc else f"since {since}") + f"  (budget left {cl.budget_left()})")''')
sub('''            if not url:
                q = ({"docket__court": court, "date_filed__gte": since} if kind == "clusters"
                     else {"cluster__docket__court": court, "cluster__date_filed__gte": since})
                q.update({"order_by": order, "page_size": str(page_size), "fields": fields})
                url = CL + path + "?" + urllib.parse.urlencode(q)
''', '''            if not url: url = first_url(court, kind, path, fields, order, since, inc, page_size)
''')
sub('''                except Exception as e:                                        # one court timing out must not cost the whole day
''', '''                except Exception as e:                                        # one court timing out must not cost the whole day
                    if inc and "HTTP 400" in str(e):                          # CourtListener refused the changed-since filter: full window, from now on
                        log(f"[{court}] changed-since filter rejected ({str(e)[:100]}); using the full window"); inc = None; cs["inc"] = None; st.d["inc_off"] = today
                        cs.pop(key, None); st.save(); url = first_url(court, kind, path, fields, order, since, None, page_size); continue
''')
sub('''            cs.pop("done", None); cs.pop("clusters_next", None); cs.pop("opinions_next", None); cs.pop("since", None); cs.pop("clusters_rows", None)''',
    '''            cs.pop("done", None); cs.pop("clusters_next", None); cs.pop("opinions_next", None); cs.pop("since", None); cs.pop("clusters_rows", None); cs.pop("inc", None)''')
shutil.copy2(p, p + ".bak-incremental"); open(p, "w", encoding="utf-8").write(s); print("patched")
