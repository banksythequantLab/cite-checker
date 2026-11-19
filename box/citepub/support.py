# -*- coding: utf-8 -*-
"""support.py - optional: for a case the brief cites WITHOUT quoting it, ask the box's local model which passage of the
real opinion supports the brief's sentence. The model only proposes. Its passage is shown only if those exact words
are in the opinion text (same string test the checker uses for quotations); whether the passage really supports the
point is left to the reader. Nothing leaves the machine: the model is the box's own Ollama on loopback."""
import json, re

SYSTEM = ("You are checking a legal brief against the actual text of a court opinion. You get the sentence(s) of the brief "
          "that cite the case, and excerpts of the opinion. Find the single passage in the OPINION (not the brief) that most "
          "directly supports the brief's proposition. Return JSON only: "
          '{"passage": "<copied EXACTLY from the opinion, 15-60 words>", "supports": "yes"|"partly"|"no", "note": "one sentence"}. '
          'If no passage supports it return {"passage": "", "supports": "no", "note": "..."}. Never paraphrase the passage. Never invent text.')
_WORD = re.compile(r"[a-z]{5,}")

def window(opinion, context, max_chars=9000, piece=700):
    """The parts of a long opinion most likely to matter: pieces sharing the most distinctive words with the brief's
    sentence, kept in their original order. Deterministic - the model never chooses what it gets to read."""
    if len(opinion) <= max_chars: return opinion
    want = set(_WORD.findall(context.lower()))
    pieces = [opinion[i:i + piece] for i in range(0, len(opinion), piece - 100)]
    scored = sorted(range(len(pieces)), key=lambda i: -len(want & set(_WORD.findall(pieces[i].lower()))))
    keep = sorted(scored[:max(1, max_chars // piece)])
    return "\n[...]\n".join(pieces[i] for i in keep)

def find(post, model, qnorm, context, opinion, timeout=45):
    body = {"model": model, "stream": False, "think": False, "format": "json",
            "options": {"temperature": 0, "num_predict": 300},          # no num_ctx: never make the box reload its model
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": "BRIEF (the citing sentence):\n%s\n\nOPINION (excerpts):\n%s" % (context[-1500:], window(opinion, context))}]}
    raw = ((post("/api/chat", body, timeout=timeout).get("message") or {}).get("content") or "").strip()
    try: d = json.loads(raw)
    except Exception:
        a, z = raw.find("{"), raw.rfind("}")
        try: d = json.loads(raw[a:z + 1]) if a != -1 else {}
        except Exception: d = {}
    passage = str(d.get("passage") or "").strip()
    ok = bool(passage) and len(qnorm(passage)) >= 25 and qnorm(passage) in qnorm(opinion)
    return {"model_supports": str(d.get("supports") or "no")[:10], "note": str(d.get("note") or "")[:300],
            "passage": {"verified": ok, "matched": passage[:600] if ok else ""}}
