#!/opt/banksy/lex/venv/bin/python
# -*- coding: utf-8 -*-
"""lex_notable.py - each morning, pick out the new decisions worth a lawyer's attention.

Runs after the daily ingest. Looks only at opinions that entered the library since the last run and scores each
with plain text rules (no model): Court of Appeals decisions, sanctions, AI / fabricated-citation cases, section 1782,
questions of first impression, departures from precedent, reversals and dissents. The top few are kept.

For each kept decision the box's own model writes ONE sentence and must back it with a sentence copied from the
opinion. That quote is string-checked against the opinion text; if it is not there word for word, the model's
sentence is thrown away and the entry shows the passage that triggered the rule instead. So every line in the
list is tied to words that are actually in the decision.

Output: notable/<date>.json + notable/latest.json (read by the morning brief), one kiosk card when there is something.
Usage:  lex_notable.py [--days N] [--top 8] [--dry]      (--days N = re-scan decisions dated in the last N days; testing)"""
import sys, os, re, json, argparse, datetime as dt
sys.path.insert(0, "/opt/banksy/lex")
import lex_ask as LX

OUT = "/opt/banksy/lex/notable"
# tag, weight, pattern (searched case-insensitively over the whole opinion unless a zone is given)
AI_W = r"(?:artificial intelligence|generative ai|\bgen ?ai\b|chatgpt|large language model|\bLLMs?\b|\bAI\b(?: tools?| programs?|-generated| generated)?)"
CITE_W = r"(?:citations?|cited|case law|cases|authorit\w+|quotations?|briefs?|filings?|submissions?)"
RULES = [
    # an AI word only counts next to a word about citing; a commercial case that merely involves an AI company is not this
    ("AI / fabricated citations", 6, r"hallucinat\w+[^.]{0,140}\b" + CITE_W + r"\b|\b" + CITE_W + r"\b[^.]{0,140}hallucinat\w+|" + AI_W + r"[^.]{0,80}hallucinat\w+|phantom citations?|(?:non-?existent|fictitious|fabricated|fake|bogus|made-up)\s+(?:cases?|citations?|authorit\w+|quotations?|decisions?|opinions?)|(?:cases?|citations?|authorit\w+|decisions?) (?:that |which )?(?:do(?:es)? not|did not|don't) exist|" + AI_W + r"[^.]{0,160}\b" + CITE_W + r"\b|\b" + CITE_W + r"\b[^.]{0,160}" + AI_W, None),
    ("section 1782", 6, r"\b28\s+U\.?\s?S\.?\s?C\.?\s+(?:§+\s*)?1782\b|section\s+1782\b|§\s*1782\b", None),
    ("first impression", 4, r"(?:issue|question|matter|case) of first impression|presents? an? novel (?:question|issue)|ha[sv]e? not (?:yet |previously )?(?:been )?(?:addressed|decided|resolved|considered)(?: th(?:is|e) (?:issue|question))? (?:by|in) this court|this court has (?:not|never) (?:yet )?(?:addressed|decided|had occasion)", None),
    # "objections are overruled" is a ruling on an objection, not on a precedent: the subject must be a case or a holding
    ("departs from precedent", 4, r"\b(?:we|this court) (?:now |hereby )?overrule (?![^.]{0,60}objection)|should no longer be followed|(?:decisions?|holdings?|precedents?|cases|rule) (?:is|are) (?:hereby |now )?(?:overruled|abrogated)|we (?:now )?decline to follow our (?:prior|earlier)", None),
    # a sanction actually sought or imposed in this case; not the standard of review, not "lawful sanctions" in immigration law
    ("sanctions", 3, r"sanctions? (?:is|are|were|was) (?:warranted|imposed|appropriate|awarded)|(?:motion|request|application) for sanctions is (?:granted|denied)|(?:we|the court) (?:hereby |now |therefore )?(?:impose|award)s? sanctions|22 NYCRR (?:§+\s*)?130-1\.1|frivolous conduct|Rule 11 sanctions (?:are|is|were)|sanctioned (?:counsel|plaintiff|defendant|the attorney)|refer\w* [^.]{0,80}Grievance (?:Panel|Committee)|order(?:ed)? to show cause why (?:he|she|they|counsel|it) should not be sanctioned", None),
    # a dissent in THIS decision; "(Smith, J., dissenting)" after a citation is someone else's
    ("dissent", 2, r"\b(?:Judge|Justice) [A-Z][\w.' -]{1,40} dissents?\b|\bdissents? in a separate|\bdissents? and votes?\b|\(dissenting\)\s*[:.]|, dissenting(?: in part)?:|dissenting from the denial of rehearing|, JJ\.,? dissent(?!ing\))", None),
    ("reversed", 1.5, r"\b(?:is|are|be|and|unanimously|judgment|order),? reversed\b|\bREVERSED\b|\bVACATED AND REMANDED\b|\breversed, on the law\b", "edges"),
]
COURT_BONUS = {"ny": ("Court of Appeals", 5), "ca2": ("2d Cir.", 1)}
SYSTEM = ("You summarize one court decision for a busy litigator. Return JSON only: "
          '{"summary": "<ONE sentence, at most 30 words: what the court decided and why it matters>", '
          '"quote": "<one sentence copied EXACTLY from the text that shows it, 12-45 words>"}. '
          "You are told why the decision was flagged; the summary must say what the court said on that point. "
          "Use only the text given. Never invent a holding. Never paraphrase the quote.")

def qnorm(s):
    s = s.lower().replace("‘", "'").replace("’", "'").replace("“", '"').replace("”", '"').replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", re.sub(r"[\[\]\"']", "", s)).strip()

def sentence_around(text, m, span=260):
    """The sentence (roughly) containing a rule hit - copied from the opinion, used as the receipt when no model line survives."""
    a = max(text.rfind(". ", 0, m.start()) + 2, m.start() - span); b = text.find(". ", m.end()); b = (b + 1) if 0 <= b < m.end() + span else m.end() + span
    return re.sub(r"\s+", " ", text[a:b]).strip()

def score(row):
    cid, name, court, date, url, text = row
    tags, pts, hits = [], 0.0, []
    if court in COURT_BONUS: tags.append(COURT_BONUS[court][0]); pts += COURT_BONUS[court][1]
    edges = text[:2500] + "\n" + text[-1500:]
    for tag, w, pat, zone in RULES:
        m = re.search(pat, edges if zone == "edges" else text, re.I)
        if not m: continue
        if tag == "section 1782" and not re.search(r"foreign|international", text, re.I): continue
        tags.append(tag); pts += w
        if zone != "edges": hits.append((w, sentence_around(text, m)))
    if len(text) > 25000: pts += 1
    hits.sort(key=lambda x: -x[0])
    return pts, tags, (hits[0][1] if hits else "")

def one_line(name, text, receipt, tags=()):
    """Model sentence + its supporting quote, kept only if the quote is in the opinion word for word."""
    body = text[:5000] + ("\n[...]\n" + receipt if receipt and receipt not in text[:5000] else "") + ("\n[...]\n" + text[-2500:] if len(text) > 7500 else "")
    try:
        r = LX.post("/api/chat", {"model": LX.CHAT, "stream": False, "think": False, "format": "json",
                                  "options": {"temperature": 0, "num_predict": 260},
                                  "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "CASE: %s\nFLAGGED FOR: %s\n\nTEXT:\n%s" % (name, ", ".join(tags) or "general interest", body)}]}, timeout=90)
        d = json.loads((r.get("message") or {}).get("content") or "{}")
    except Exception:
        return "", "", False
    summary, quote = str(d.get("summary") or "").strip()[:300], str(d.get("quote") or "").strip()[:500]
    ok = bool(summary) and len(qnorm(quote)) >= 40 and qnorm(quote) in qnorm(text)
    return (summary, quote, True) if ok else ("", "", False)

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--days", type=int, default=0); ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--min", type=float, default=4.0); ap.add_argument("--dry", action="store_true"); a = ap.parse_args()
    conn = LX.db(); os.makedirs(OUT, exist_ok=True); today = dt.date.today().isoformat()
    if a.days:
        rows = conn.execute("select id::text, case_name, court_id, decision_date, source_url, text_plain from opinions "
                            "where decision_date >= current_date - %s::int and length(text_plain) > 1500", (a.days,)).fetchall()
    else:
        last = None
        try: last = json.load(open(os.path.join(OUT, "latest.json"))).get("generated")
        except Exception: pass
        since = last or (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=26)).isoformat()
        rows = conn.execute("select id::text, case_name, court_id, decision_date, source_url, text_plain from opinions "
                            "where created_at > %s::timestamptz and decision_date >= current_date - 120 and length(text_plain) > 1500", (since,)).fetchall()
    scored = []
    for row in rows:
        pts, tags, receipt = score(row)
        if pts >= a.min: scored.append((pts, tags, receipt, row))
    scored.sort(key=lambda x: (-x[0], str(x[3][3])))
    items = []
    for pts, tags, receipt, (cid, name, court, date, url, text) in scored[:a.top]:
        summary, quote, ok = one_line(name, text, receipt, tags)
        items.append({"id": cid, "case_name": name, "court": LX.COURT.get(court, court) if hasattr(LX, "COURT") else court, "date": str(date), "url": url or "",
                      "tags": tags, "score": pts, "summary": summary, "quote": quote if ok else receipt[:400], "model_line": ok,
                      "why": receipt[:400]})          # the sentence that tripped the rule, copied from the opinion
    res = {"generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "day": today, "scanned": len(rows), "flagged": len(scored), "items": items}
    for it in items:
        print("%-5.1f %s (%s, %s) [%s]" % (it["score"], it["case_name"][:70], it["court"], it["date"], ", ".join(it["tags"])))
        print("      %s" % (it["summary"] or "(no model line survived the quote check)"))
        print("      “%s”" % it["quote"][:220])
        if it["why"] and it["why"] != it["quote"]: print("      flagged passage: “%s”" % it["why"][:220])
    print("scanned %d new decisions, %d flagged, %d listed" % (len(rows), len(scored), len(items)))
    if a.dry: return
    json.dump(res, open(os.path.join(OUT, today + ".json"), "w"), indent=1, ensure_ascii=False)
    json.dump(res, open(os.path.join(OUT, "latest.json"), "w"), indent=1, ensure_ascii=False)
    try:
        sys.path.insert(0, "/opt/banksy/assistant"); import audit
        audit.log("lex", "notable", scanned=len(rows), flagged=len(scored), listed=len(items))
    except Exception: pass
    if items:
        try:
            import boxio
            txt = "%d new decision%s worth a look: " % (len(items), "" if len(items) == 1 else "s") + "; ".join("%s (%s)" % (i["case_name"][:48], ", ".join(i["tags"][:2])) for i in items[:3])
            boxio.nudge("lex", "lex-notable:" + today, (txt + ". Full list in the morning brief.")[:300])
        except Exception as e: print("card failed: %s" % e, file=sys.stderr)

if __name__ == "__main__":
    main()
