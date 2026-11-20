p="/opt/banksy/lex/lex_ingest.py"; s=open(p,encoding="utf-8").read()
a='''                    log(f"429: sleeping {wait}s"); time.sleep(wait); continue'''
b='''                    if wait > 900:                                            # the day's allowance is gone: stop fetching, do not sleep for hours holding the lex lock
                        log(f"429: allowance exhausted (next request allowed in {wait}s); stopping fetch for today"); raise BudgetExhausted()
                    log(f"429: sleeping {wait}s"); time.sleep(wait); continue'''
assert s.count(a)==1
import shutil; shutil.copy2(p, p+".bak-429")
open(p,"w",encoding="utf-8").write(s.replace(a,b)); print("patched")
