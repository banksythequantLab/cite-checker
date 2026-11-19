#!/usr/bin/env bash
# smoke test of the public citation checker on the box: health + a mixed NY / federal / statute brief
U=${1:-http://127.0.0.1:8124}
curl -s -m 15 $U/api/health; echo
curl -s -m 280 -X POST $U/api/check --form-string "text=$(cat ${2:-/opt/banksy/lex/citepub/smoke_brief.txt})" | /usr/bin/python3 -c "
import json,sys
d=json.load(sys.stdin)
if not d.get('ok'): print('FAILED', d); sys.exit(1)
print(d['counts'])
for c in d['citations']:
    print(' %-11s| %s | %s | %s | %s' % (c['status'], (c['case_name_in_brief'] or '')[:40], c['citation'][:42], (c.get('cl_case_name') or '')[:50], [q['state'] for q in c['quotes']]))
    for n in c['notes'][:2]: print('              - ' + n[:150])"
