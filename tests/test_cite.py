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


def test_quote_survives_star_pagination_and_footnote_markers():
    doc = ("the accepted rule that a complaint should not be dismissed for failure to state a claim "
           "unless it appears beyond doubt that the plaintiff can prove no set of facts *46 in support "
           "of his claim which would entitle him to relief. 5 Here, the complaint alleged")
    q = "unless it appears beyond doubt that the plaintiff can prove no set of facts in support of his claim which would entitle him to relief"
    r = spans.verify(doc, q)
    assert r["verified"], r
    assert r["matched"].startswith("unless it appears") and r["matched"].endswith("to relief")
    # curly quotes / dashes in the brief vs straight in the opinion
    r2 = spans.verify('he said "no set of facts" — twice, and that\'s all', "he said “no set of facts” – twice, and that’s all")
    assert r2["verified"]
    # a real number inside the quote still has to match
    assert not spans.verify("damages of 400 dollars were awarded", "damages of 500 dollars were awarded")["verified"]
    assert spans.verify("damages of 400 dollars were awarded", "damages of 400 dollars were awarded")["verified"]


def test_extract_docx_includes_footnotes_and_refuses_bombs(tmp_path):
    import io, zipfile, extract_file as X
    W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    def doc(body):
        return f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>'
    def para(t): return f'<w:p><w:r><w:t>{t}</w:t></w:r></w:p>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", doc(para("See Bell Atlantic Corp. v. Twombly, 550 U.S. 544 (2007).")))
        z.writestr("word/footnotes.xml", f'<w:footnotes xmlns:w="{W}">{para("Ashcroft v. Iqbal, 556 U.S. 662 (2009).")}</w:footnotes>')
    text = X.extract("brief.docx", buf.getvalue())
    assert "550 U.S. 544" in text and "556 U.S. 662" in text
    assert len(EX.extract(text)) == 2
    # a docx that declares a huge expansion is refused before anything is parsed
    bomb = io.BytesIO()
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", b"\0" * (X.MAX_DOCX_UNCOMPRESSED + 1))
    try:
        X.extract("bomb.docx", bomb.getvalue()); assert False, "bomb accepted"
    except X.ExtractError as e:
        assert "cap" in str(e)
    assert X.extract("b.txt", b"Twombly, 550 U.S. 544").startswith("Twombly")


def test_extract_pdf():
    import extract_file as X
    from pypdf import PdfWriter
    import io
    w = PdfWriter(); page = w.add_blank_page(width=612, height=792)
    # pypdf can't lay out text without a font resource; use an annotation-free
    # minimal content stream via a generated page is overkill -- just check caps/errors
    out = io.BytesIO(); w.write(out)
    try:
        X.extract("empty.pdf", out.getvalue()); assert False
    except X.ExtractError as e:
        assert "no extractable text" in str(e)


def test_rate_limit_per_ip(monkeypatch):
    import ratelimit as RL
    monkeypatch.setitem(RL.LIMITS, "/api/check", (2, 3))
    RL._hits.clear()
    assert RL.check("/api/check", "1.2.3.4")[0]
    assert RL.check("/api/check", "1.2.3.4")[0]
    ok, why = RL.check("/api/check", "1.2.3.4"); assert not ok and "per minute" in why
    assert RL.check("/api/check", "5.6.7.8")[0]          # another address is unaffected
    assert RL.check("/api/health", "1.2.3.4")[0]         # unlimited route
    assert RL.client_ip({"x-forwarded-for": "9.9.9.9, 10.0.0.1"}, "10.0.0.1") == "9.9.9.9"


def test_parenthetical_quote_belongs_to_preceding_cite():
    # Bluebook explanatory parentheticals follow the cite; they must not be
    # attributed to the NEXT cite (that produced a false MISQUOTE on Conley).
    import extract
    t = ('Bell Atlantic Corp. v. Twombly, 550 U.S. 544 (2007) ("state a claim to relief '
         'that is plausible on its face"). Conley v. Gibson, 355 U.S. 41 (1957). '
         'Ashcroft v. Iqbal, 556 U.S. 662, 678 (2009) (quoting Twombly, 550 U.S. at 570) '
         '("Threadbare recitals of the elements of a cause of action will not do"). '
         '"A pleading must contain more than labels." '
         'Chambers v. Time Warner, Inc., 282 F.3d 147, 152 (2d Cir. 2002).')
    got = {c.key: c.quotes for c in extract.extract(t)}
    assert got["550 U.S. 544"] == ["state a claim to relief that is plausible on its face"]
    assert got["355 U.S. 41"] == []
    assert got["556 U.S. 662"] == ["Threadbare recitals of the elements of a cause of action will not do"]
    assert got["282 F.3d 147"] == ["A pleading must contain more than labels."]


def test_nested_cite_in_parenthetical_is_still_extracted():
    import extract
    t = 'Doe v. Roe, 100 F.3d 1 (2d Cir. 1996) (citing Fake v. Fake, 999 F.3d 999 (2d Cir. 2020)).'
    assert [c.key for c in extract.extract(t)] == ["100 F.3d 1", "999 F.3d 999"]
