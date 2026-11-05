import re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cite"))
import extract as EX, verify as V, spans

SAMPLE = re.search(r"const SAMPLE=`(.*?)`;", (ROOT/"ui"/"index.html").read_text(), re.S).group(1)

def test_demo_brief_extracts_five_distinct_citations():
    keys = [c.key for c in EX.extract(SAMPLE)]
    assert keys == ["550 U.S. 544", "556 U.S. 662", "925 F.3d 1339",
                    "2019 WL 4639462", "282 F.3d 147"]

def test_repeat_cite_merges_its_quotes_instead_of_dropping():
    """The second Twombly cite carries the fabricated quote; it must be checked."""
    tw = next(c for c in EX.extract(SAMPLE) if c.key == "550 U.S. 544")
    assert len(tw.quotes) == 2
    assert any("clear and convincing" in q for q in tw.quotes)

def test_quotes_attach_to_the_following_cite_only():
    iq = next(c for c in EX.extract(SAMPLE) if c.key == "556 U.S. 662")
    assert len(iq.quotes) == 1 and "Threadbare" in iq.quotes[0]
    va = next(c for c in EX.extract(SAMPLE) if c.key == "925 F.3d 1339")
    assert va.quotes == []

def test_case_names_are_clean():
    names = {c.key: c.case_name for c in EX.extract(SAMPLE)}
    assert names["556 U.S. 662"] == "Ashcroft v. Iqbal"
    assert names["925 F.3d 1339"] == "Varghese v. China Southern Airlines Co"
    assert names["282 F.3d 147"] == "Chambers v. Time Warner, Inc"

def test_in_re_names_and_leading_prose():
    b = "The court in Ashcroft v. Iqbal, 556 U.S. 662 (2009), and In re Enron Corp. Sec. Litig., 235 F. Supp. 2d 549 (S.D. Tex. 2002), agreed."
    names = [c.case_name for c in EX.extract(b)]
    assert names == ["Ashcroft v. Iqbal", "In re Enron Corp. Sec. Litig"]

def test_name_match_handles_legal_abbreviations():
    assert V.names_match("In re Enron Corp. Sec. Litig.", "In re Enron Corporation Securities Litigation")
    assert V.names_match("Bell Atlantic Corp. v. Twombly", "Bell Atlantic Corp. v. Twombly")
    assert not V.names_match("Varghese v. China Southern Airlines Co.", "United States v. Johnson")

def test_verbatim_quote_check():
    op = "To survive a motion to dismiss, a complaint must contain sufficient factual matter to state a claim to relief that is plausible on its face."
    assert spans.verify(op, "state a claim to relief that is plausible on its face")["verified"]
    assert not spans.verify(op, "prove each element by clear and convincing evidence")["verified"]


def test_lookup_cache_spends_quota_once(tmp_path, monkeypatch):
    import courtlistener as CL
    monkeypatch.setattr(CL, "_DB", str(tmp_path / "c.db"))
    calls = []
    def fake_lookup(text):
        calls.append(text)
        return [{"citation": "550 U.S. 544", "normalized_citations": ["550 U.S. 544"],
                 "status": 200, "clusters": [{"id": 1}]}]
    monkeypatch.setattr(CL, "lookup", fake_lookup)
    a = CL.lookup_cites(["550 U.S. 544", "925 F.3d 1339"])
    b = CL.lookup_cites(["550 U.S. 544", "925 F.3d 1339"])
    assert len(calls) == 1, "second run must be served from the cache"
    assert "925 F.3d 1339" in calls[0] and "550 U.S. 544" in calls[0]
    nf = [r for r in b if r["citation"] == "925 F.3d 1339"][0]
    assert nf["status"] == 404 and not nf["clusters"]
    assert [r["citation"] for r in a] == [r["citation"] for r in b]


def test_throttled_api_with_local_index_degrades_per_cite(tmp_path, monkeypatch):
    import courtlistener as CL, bulk
    monkeypatch.setattr(CL, "_DB", str(tmp_path / "c.db"))
    db = str(tmp_path / "cl.db"); c = bulk._db(db)
    c.execute("INSERT INTO citations VALUES('550','U.S.','544',145,1)")
    c.execute("INSERT INTO clusters VALUES(145,'Bell Atlantic Corp. v. Twombly','','2007-05-21','x','Published')")
    c.commit(); c.close()
    monkeypatch.setenv("CITE_BULK_DB", db); monkeypatch.setattr(bulk, "_Q", None)
    monkeypatch.setattr(CL, "lookup", lambda t: (_ for _ in ()).throw(CL.CLError("HTTP 429 throttled")))
    out = CL.lookup_cites(["550 U.S. 544", "925 F.3d 1339"])
    by = {r["citation"]: r for r in out}
    assert by["550 U.S. 544"]["status"] == 200 and by["550 U.S. 544"]["source"] == "bulk"
    assert by["925 F.3d 1339"]["status"] == 404 and "could not be asked" in by["925 F.3d 1339"]["error_message"]
    # and the throttled miss was NOT cached as a 404
    assert CL._lk_db().execute("select count(*) from lookups").fetchone()[0] == 0
