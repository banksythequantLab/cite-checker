"""
For a citation the brief paraphrases (no quotation marks), ask the model to
find the passage in the REAL opinion that supports the brief's proposition.
The model returns a verbatim span; it is verified against the opinion text.
So the model can only ever point at words that are actually in the case --
whether those words support the proposition is left to the human, on screen.
"""
from __future__ import annotations

import json
import re

import spans
from inference import Vultr

SYSTEM = """You are checking a legal brief against the actual text of a court
opinion. You will be given the sentence(s) in the brief that cite the case,
and the opinion's text. Find the single passage in the OPINION (not the
brief) that most directly supports the brief's proposition.

Return JSON only: {"passage": "<copied EXACTLY from the opinion, 15-60 words>",
"supports": "yes"|"partly"|"no", "note": "one sentence"}.
If no passage supports it, return {"passage": "", "supports": "no", "note": "..."}.
Never paraphrase the passage. Never invent text."""


def find_support(inf: Vultr, brief_context: str, opinion: str) -> dict:
    resp = inf.client.chat.completions.create(
        model=inf.model, temperature=0, max_tokens=500,
        messages=[{"role": "system", "content": SYSTEM},
                  {"role": "user", "content":
                   f"BRIEF (the citing sentence):\n{brief_context[:1500]}\n\n"
                   f"OPINION:\n{opinion[:28000]}"}])
    raw = (resp.choices[0].message.content or "").strip()
    b = raw
    if "```" in b:
        b = max(b.split("```"), key=len).removeprefix("json").strip()
    try:
        d = json.loads(b)
    except json.JSONDecodeError:
        a, z = b.find("{"), b.rfind("}")
        d = json.loads(b[a:z + 1]) if a != -1 else {}
    passage = str(d.get("passage", "")).strip()
    chk = spans.verify(opinion, passage) if passage else {"verified": False, "reason": "no passage"}
    return {"model_supports": str(d.get("supports", "no")),
            "note": str(d.get("note", "")),
            "passage": chk}
