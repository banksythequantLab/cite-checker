#!/bin/bash
# cite_regress.sh - one command to prove the citation checker still behaves after any change.   exit 0 = all good
#  1. the test draft gives exactly the saved result (tests/expected_draft.txt)
#  2. real New York opinions (4 random samples, ~800 citations): none may come back WRONG CASE or NOT FOUND
#  3. with the nationwide index installed: the mixed brief gives the saved statuses (tests/expected_smoke.txt)
# After an INTENDED change in behaviour, re-save the expectations with:  cite_regress.sh --accept
cd /opt/banksy/lex || exit 2; PY=./venv/bin/python; fail=0
draft(){ $PY cite_check.py tests/cite_test_draft.txt 2>&1 | sed '$d'; }
smoke(){ $PY cite_check.py citepub/smoke_brief.txt --json 2>/dev/null | $PY -c "
import json,sys
for c in json.load(sys.stdin)['citations']: print(c['status'], '|', c.get('name') or c.get('kind'), '|', c['cite'], '|', [q['result'] for q in c.get('quotes', [])])"; }
have_nat(){ [ -f national/READY ] && [ -f citepub/smoke_brief.txt ]; }
if [ "${1:-}" = "--accept" ]; then
  draft > tests/expected_draft.txt; have_nat && smoke > tests/expected_smoke.txt
  echo "expectations saved"; exit 0
fi
if diff <(draft) tests/expected_draft.txt > /tmp/cite_regress_draft.diff; then echo "1 test draft: same as expected"; else echo "1 test draft: CHANGED (see /tmp/cite_regress_draft.diff)"; fail=1; fi
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
[ $fail -eq 0 ] && echo "CITE REGRESS: PASS" || echo "CITE REGRESS: FAIL"; exit $fail
