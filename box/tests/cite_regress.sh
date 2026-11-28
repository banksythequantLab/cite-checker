#!/bin/bash
# cite_regress.sh - one command to prove the citation checker still behaves after any change.   exit 0 = all good
#  1. the test draft gives exactly the saved result (tests/expected_draft.txt)
#  2. real New York opinions (4 random samples, ~800 citations): none may come back WRONG CASE or NOT FOUND
#  3. with the nationwide index installed: the mixed brief gives the saved statuses (tests/expected_smoke.txt)
# After an INTENDED change in behaviour, re-save the expectations with:  cite_regress.sh --accept
cd /opt/banksy/lex || exit 2; PY=./venv/bin/python; fail=0
counts(){ sed -E "s/in [0-9]+ opinions/in N opinions/; s/\([0-9]+ times\)/(N times)/"; }   # the library grows daily: how often a cite is printed is not a regression
draft(){ $PY cite_check.py tests/cite_test_draft.txt 2>&1 | sed '$d'; }
smoke(){ $PY cite_check.py citepub/smoke_brief.txt --json 2>/dev/null | $PY -c "
import json,sys
for c in json.load(sys.stdin)['citations']: print(c['status'], '|', c.get('name') or c.get('kind'), '|', c['cite'], '|', [q['result'] for q in c.get('quotes', [])])"; }
have_nat(){ [ -f national/READY ] && [ -f citepub/smoke_brief.txt ]; }
if [ "${1:-}" = "--accept" ]; then
  draft > tests/expected_draft.txt; have_nat && smoke > tests/expected_smoke.txt
  echo "expectations saved"; exit 0
fi
if diff <(draft | counts) <(counts < tests/expected_draft.txt) > /tmp/cite_regress_draft.diff; then echo "1 test draft: same as expected"; else echo "1 test draft: CHANGED (see /tmp/cite_regress_draft.diff)"; fail=1; fi
bad=0; n=0
for s in "" q7 zz m3; do
  out=$(SALT=$s bash tests/cite_falsealarm.sh 2>&1); t=$(echo "$out" | grep '^TOTAL')
  n=$((n + $(echo "$t" | grep -o "[0-9]\+" | head -n -1 | awk '{s+=$1}END{print s+0}')))
  b=$(echo "$out" | grep -c -E '^  (mismatch|not_found) '); bad=$((bad + b))
  [ "$b" -gt 0 ] && echo "$out" | grep -A3 -E '^  (mismatch|not_found) ' | cut -c1-200
done
if [ $bad -eq 0 ]; then echo "2 real opinions: $n citations, no false WRONG CASE / NOT FOUND"; else echo "2 real opinions: $bad FALSE ALARMS in $n citations"; fail=1; fi
if have_nat && [ -f tests/expected_smoke.txt ]; then
  if diff <(smoke) tests/expected_smoke.txt > /tmp/cite_regress_smoke.diff; then echo "3 nationwide brief: same as expected"; else echo "3 nationwide brief: CHANGED (see /tmp/cite_regress_smoke.diff)"; fail=1; fi
else echo "3 nationwide brief: skipped (nationwide index not installed)"; fi
# 4. citations a court lists as nonexistent (Phoenix Fashion v. Saadia, 2d Cir. Nov 17 2026) must not be verified by that very
#    decision, while real cases cited in the same sanctions context still verify (bug found Nov 28 2026)
if grep -q "Phoenix Fashion" <(echo "select 1" >/dev/null; $PY -c "import sys;sys.path.insert(0,'.');import lex_ask as L;print(L.db().execute(\"select count(*) from opinions where case_name ilike 'Phoenix Fashion%Saadia%'\").fetchone()[0] and 'Phoenix Fashion')" 2>/dev/null); then
  printf '%s\n' "XYZ Corp. v. ABC Inc., 987 F.3d 123 (2d Cir. 2022); Doe v. Smith, 456 F.3d 789 (2d Cir. 2021); Smith v. Jones, 789 F.2d 123 (2d Cir. 2021). Park v. Kim, 91 F.4th 610 (2d Cir. 2024); Mata v. Avianca, Inc., 678 F. Supp. 3d 443 (S.D.N.Y. 2023)." > /tmp/cite_regress_fake.txt
  got=$($PY cite_check.py /tmp/cite_regress_fake.txt --json 2>/dev/null | $PY -c "import json,sys;print(' '.join(c['status'] for c in json.load(sys.stdin)['citations']))")
  if [ "$got" = "not_found not_found not_found verified verified" ]; then echo "4 fabricated citations a court disavowed: flagged, real ones verified"; else echo "4 fabricated citations a court disavowed: WRONG ($got)"; fail=1; fi
else echo "4 fabricated citations: skipped (Phoenix Fashion order not in the library)"; fi
[ $fail -eq 0 ] && echo "CITE REGRESS: PASS" || echo "CITE REGRESS: FAIL"; exit $fail
