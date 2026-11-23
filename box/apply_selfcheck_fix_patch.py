import shutil
# 1) morning brief: the notable and cite-usage sections read live box files, so keep them out of the unit test's temp box
p = "/opt/banksy/mailguard/morning_brief.py"; s = open(p, encoding="utf-8").read()
real = '(os.environ.get("BANKSY_NAS", "/opt/banksy/nas").rstrip("/") == "/opt/banksy/nas")'
a = 'nl = _notable() if _on("notable") else []'; b = 'nl = _notable() if (_on("notable") and %s) else []' % real
assert s.count(a) == 1; s = s.replace(a, b)
a = 'cu = _cite_usage() if (_weekday() == 0 and _on("citeusage")) else []'; b = 'cu = _cite_usage() if (_weekday() == 0 and _on("citeusage") and %s) else []' % real
assert s.count(a) == 1; s = s.replace(a, b)
shutil.copy2(p, p + ".bak-realbox"); open(p, "w", encoding="utf-8").write(s)
# 2) claw fence test: the Nov 17 ollama gate (127.0.0.1:11436) is an allowed port in both fences; the test never learned it
p = "/opt/banksy/tests/test_clawfence19.py"; s = open(p, encoding="utf-8").read()
for a, b in (('"tcp dport { 11434, 8080, 8082, 18789-18899 }"', '"tcp dport { 11434, 11436, 8080, 8082, 18789-18899 }"'),
             ('"tcp dport { 11434, 8082, 18789 }"', '"tcp dport { 11434, 11436, 8082, 18789 }"')):
    assert s.count(a) == 1; s = s.replace(a, b)
shutil.copy2(p, p + ".bak-gate"); open(p, "w", encoding="utf-8").write(s); print("patched both")
