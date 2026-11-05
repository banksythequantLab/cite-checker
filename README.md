# Cite Checker

**Every citation in a brief, checked against the real opinion. The model proposes; strings and CourtListener decide; a lawyer reviews every flag.**

Built for the [Vultr: Agent Rush Hackathon](https://lablab.ai/ai-hackathons/vultr-hackathon) — Challenge 1, *Blast Radius Zero*.

---

## Why

In *Mata v. Avianca, Inc.*, No. 22-cv-1461 (PKC) (S.D.N.Y. June 22, 2023), lawyers filed a brief citing six cases that did not exist. ChatGPT had invented them, complete with reporter cites, and nobody checked. The court sanctioned the lawyers. It keeps happening: fabricated citations, real cases cited for things they never said, quotes that are not in the opinion.

Checking is tedious and exactly the kind of thing a machine should do — provided the machine cannot itself make things up. So this tool is built so that **nothing a model says ever reaches the reviewer unverified**.

## What it does

Paste a brief. For every case citation:

| status | meaning | who decides |
|---|---|---|
| **VERIFIED** | exists, same case the brief names, every quoted passage is in the opinion verbatim | CourtListener + string match |
| **MISQUOTE** | exists, right case, but a quoted passage is **not** in the opinion | string match |
| **WRONG CASE** | the cite resolves to a different case than the brief names | CourtListener |
| **NOT IN CL** | not in CourtListener's database — *a coverage statement, not a fabrication verdict* (see below) | CourtListener |
| **AMBIGUOUS** | several cases share that reporter page and the name doesn't settle it | CourtListener |
| **UNQUOTED** | exists, right case, nothing quoted — a model then *proposes* the supporting passage, which is checked verbatim before it is shown | model → string match |
| **UNVERIFIABLE** | exists, but the opinion text could not be fetched; quotes are **not graded** | — |

The last row matters. The worst thing this tool could do is brand a real quote a misquote because a fetch failed. It will not grade against nothing.

**NOT IN CL is not "fabricated."** CourtListener's coverage is incomplete — many unpublished, Westlaw-only and state decisions are absent. Every such finding tells the reviewer to confirm in Westlaw or Lexis before relying on the case or striking it.

## Where the model is, and isn't

- **Citation extraction**: deterministic regex. No model.
- **Existence and identity**: CourtListener's citation-lookup API. No model.
- **Quotes**: whitespace-insensitive verbatim string match against the opinion text. No model.
- **Supporting passages for paraphrased cites**: a model (Vultr Serverless Inference, `glm-5.3-flash`) proposes a passage and says whether it supports the proposition. The passage is then string-matched against the opinion; if it is not there verbatim, it is discarded and the reviewer sees "no verifiable supporting passage found." The model's opinion of *support* is shown as the model's opinion, labelled as such.

## Live result on the demo brief

The demo brief is seeded with two of the Avianca fabrications and one invented Twombly quote. A live run against CourtListener returned:

```
Bell Atlantic Corp. v. Twombly, 550 U.S. 544     MISQUOTE
   ✓ "state a claim to relief that is plausible on its face."        in the opinion
   ✗ "a plaintiff must prove each element of the claim by clear
      and convincing evidence at the pleading stage"                 NOT in the opinion
Ashcroft v. Iqbal, 556 U.S. 662                  VERIFIED  ("Threadbare recitals…")
Varghese v. China Southern Airlines, 925 F.3d 1339   NOT IN CL   (Avianca fabrication, ¶26 of the sanctions order)
Martinez v. Delta Air Lines, 2019 WL 4639462         NOT IN CL   (Avianca fabrication, ¶36)
Chambers v. Time Warner, Inc., 282 F.3d 147      UNQUOTED  (resolved to cluster 7103595)
```

## Blast radius zero

The app runs on a Vultr Cloud Compute instance in a container that is read-only, unprivileged (`nobody`), every capability dropped, `no-new-privileges`, 512 MB, 128 pids. Its network is a Docker **internal** bridge: the kernel gives it no route off the host at all. The only door out is `deploy/egress-proxy`, a 90-line CONNECT proxy that allows exactly two hostnames on 443 — `courtlistener.com` and `api.vultrinference.com` — and refuses everything else **by hostname**, logging each refusal as a JSON line. (An earlier version pinned IPs with ipset; CourtListener sits behind CloudFront and the IPs rotated out from under it within hours. Hostnames are the right primitive.) Caddy terminates TLS on a separate bridge.

`deploy/verify_egress.sh` is the sealing proof. It runs probes *inside* the app container: direct sockets to `1.1.1.1` and to CourtListener are refused by the kernel; through the proxy the two allowed hosts answer; `example.com` and an invented exfil host are refused and appear in the egress log by name; the filesystem is read-only; the process cannot escalate.

## Vultr services

| service | role |
|---|---|
| **Vultr Cloud Compute** | runs the control plane (FastAPI), the sandboxed app container, the egress proxy, and Caddy |
| **Vultr Serverless Inference** | the only model call — proposing supporting passages — via the OpenAI-compatible endpoint at `https://api.vultrinference.com/v1`; model IDs resolved live |

## Run it

```bash
pip install -r requirements.txt
cp .env.example .env            # COURTLISTENER_TOKEN, VULTR_INFERENCE_API_KEY
uvicorn app:app --app-dir cite --port 8120
python3 -m pytest tests/ -q     # 7 tests, no network
```

Deploy to Vultr: put `VULTR_API_KEY` in `.env` and run `python3 deploy/vultr_create.py`. It renders `deploy/cloud-init.sh` as user data; the instance installs Docker, clones this repo and brings up the stack. Then run `bash deploy/verify_egress.sh` on the instance.

CourtListener's free tier is **125 opinion requests per day**; results are cached in SQLite so a re-check is free. The product version loads CourtListener's bulk opinion dump onto Vultr Block Storage and never hits the quota.

## Limits, stated plainly

- CourtListener coverage is incomplete; NOT IN CL means exactly that.
- The regex handles federal and New York reporters plus WL. Other state reporters are not yet parsed.
- Pin cites are extracted but not yet checked against page breaks.
- The support pass is advisory. A verified passage proves the words are in the opinion, not that the proposition is good law.

## License

MIT — Banksy AI LLC. See [LICENSE](LICENSE).
