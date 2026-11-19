#!/usr/bin/env python3
"""apply_ingest_resilience_patch.py - keep the daily New York ingest from losing a day to one bad court.

Before: a CourtListener timeout on any one court raised out of fetch(), so that day's merge and embed never ran
(9 of 49 runs died this way, and what had been fetched sat unmerged). Also one court's start date had drifted
almost a year back, which is the query that kept timing out.
After:  1. a court that errors is skipped for the day and logged; the other courts continue
        2. merge and embed always run, even if fetching failed part-way
        3. no court asks for more than 45 days back (the quarterly bulk catch-up covers anything older)
        4. if any core court has gone 14 days without a complete fetch, the box raises a card saying the free
           CourtListener allowance is no longer keeping New York current (Derek's rule for buying the $10 tier)
Usage: apply_ingest_resilience_patch.py /opt/banksy/lex/lex_ingest.py     (keeps .bak-resilience)"""
import sys, shutil
path = sys.argv[1]; s = open(path, encoding="utf-8").read()
if "skipped today" in s: print("already patched"); sys.exit(0)
out = s
def sub(old, new, label):
    global out
    if out.count(old) != 1: print("ANCHOR %s matched %d times - nothing written" % (label, out.count(old))); sys.exit(2)
    out = out.replace(old, new)

sub('''    return (base - dt.timedelta(days=7)).isoformat()''',
    '''    return max(base - dt.timedelta(days=7), dt.date.today() - dt.timedelta(days=45)).isoformat()   # never ask for more than 45 days''', "since-cap")
sub('''    if cs.get("since") and not cs.get("done"): return cs["since"]   # resume same window''',
    '''    cap = (dt.date.today() - dt.timedelta(days=45)).isoformat()
    if cs.get("since") and not cs.get("done") and cs["since"] >= cap: return cs["since"]   # resume same window (unless it has drifted too far back)
    if cs.get("since") and cs["since"] < cap: cs.pop("clusters_next", None); cs.pop("opinions_next", None); cs.pop("clusters_rows", None)''', "since-resume")
sub('''def fetch(conn, cl, st, courts, since_override, max_pages, page_size):
    for court in courts:
        cs = st.court(court)''', '''def fetch(conn, cl, st, courts, since_override, max_pages, page_size):
    all_ok = True
    for court in courts:
        skipped = False
        cs = st.court(court)''', "fetch-head")
sub('''                try: page = cl.get(url)
                except BudgetExhausted:
                    log(f"[{court}] daily budget reached during {kind}; resume tomorrow"); st.save(); return False''',
    '''                try: page = cl.get(url)
                except BudgetExhausted:
                    log(f"[{court}] daily budget reached during {kind}; resume tomorrow"); st.save(); return False
                except Exception as e:                                        # one court timing out must not cost the whole day
                    log(f"[{court}] skipped today during {kind}: {str(e)[:120]}"); st.save(); skipped = True; break''', "court-skip")
sub('''            if url: log(f"[{court}] {kind} paused at --max-pages"); return False
        cs["done"] = today; st.save(); log(f"[{court}] fetch complete")
    return True''', '''            if skipped: break
            if url: log(f"[{court}] {kind} paused at --max-pages"); return False
        if skipped: all_ok = False; continue
        cs["done"] = today; st.save(); log(f"[{court}] fetch complete")
    return all_ok''', "fetch-tail")
sub('''    if a.stage in ("fetch", "all"): summary["fetch_complete"] = fetch(conn, cl, st, courts, a.since, a.max_pages, a.page_size)''',
    '''    if a.stage in ("fetch", "all"):
        try: summary["fetch_complete"] = fetch(conn, cl, st, courts, a.since, a.max_pages, a.page_size)
        except Exception as e:                                                # still merge + embed what was fetched
            conn.rollback(); summary["fetch_complete"] = False; summary["fetch_error"] = str(e)[:160]; log("fetch stopped: " + str(e)[:160])''', "main-fetch")
sub('''    log("=== LEX_INGEST_DONE " + json.dumps(summary) + " ===")''',
    '''    summary["behind"] = coverage_alarm(st)
    log("=== LEX_INGEST_DONE " + json.dumps(summary) + " ===")''', "main-done")
sub('''            cs.pop("done", None); cs.pop("clusters_next", None)''',
    '''            if cs.get("done"): cs["last_done"] = cs["done"]              # remember the last complete day across the reset
            cs.pop("done", None); cs.pop("clusters_next", None)''', "last-done")
sub('''# ---------------- main ----------------''', '''CORE = ("ny", "nyappdiv", "nyappterm", "ca2", "nysd", "nyed")
def coverage_alarm(st, days=14):
    """Core courts whose last COMPLETE fetch is `days` or more old. If any, raise one card (once per week per court set):
    the free CourtListener allowance is not keeping New York current - Derek's rule is to move to the $10/month tier."""
    today = dt.date.today(); behind = []
    for c in CORE:
        cs = st.court(c)
        d = cs.get("done") or cs.get("last_done") or today.isoformat()        # no record yet: the two-week clock starts today
        cs["last_done"] = d
        age = (today - dt.date.fromisoformat(d)).days
        if age >= days: behind.append("%s (%d days)" % (c, age))
    st.save()
    if behind:
        try:
            sys.path.insert(0, "/opt/banksy/assistant"); import boxio
            boxio.nudge("lex", "lex-behind:%s" % today.strftime("%G-%V"),
                        "New York case law has not fully updated for two weeks: %s. The free CourtListener allowance is not enough. "
                        "Your rule: move to the $10/month tier at free.law/membership." % ", ".join(behind))
        except Exception as e: log("coverage card failed: %s" % e)
    return behind

# ---------------- main ----------------''', "alarm")
shutil.copy2(path, path + ".bak-resilience"); open(path, "w", encoding="utf-8").write(out); print("patched; backup at %s.bak-resilience" % path)
