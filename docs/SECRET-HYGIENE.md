# SECRET HYGIENE

How credentials are handled in this project, and what happened when they were not.

## The rules this repo follows

1. **No secret is ever committed.** `.env` is gitignored, the toolkit copy excludes it, and a
   pattern scan (`oc_sk_`, `ghp_`, `github_pat_`, `gsk_`, `sk-proj-`, `tvly-`, …) runs over the tree
   before any push. The published repo contains zero credentials — that was checked, not assumed.
2. **A secret is written without being echoed.** `scripts/set-key.sh NAME` reads the value on stdin,
   applies `chmod 600`, and never prints it, never logs it and never passes it as an argument
   (arguments are visible in `ps`).
3. **`env` reports names, never values.** `zen-agent env` is the supported way to ask "does this
   machine hold a credential?" — the answer is `●` or `○`, not the key.
4. **A credential that transited a chat is a credential you rotate.** This is the rule that was
   actually violated in practice (see below).
5. **Credentials get audited, not trusted.** `tools/audit-keys.py` probes every credential at its
   provider and records the verdict with the HTTP evidence.

## Auditing without spending money

The audit distinguishes three things that are easy to conflate: *unreachable*, *rejected*, and *fine*.

- A `GET /models` with a Bearer token is the cheapest possible check: 200 means live, 401/403 means dead.
- For endpoints without a free read, the probe sends a **deliberately empty body**. A `400`/`422`
  there means the credential was accepted and the *request* was wrong, while `401`/`403` means the
  credential is dead. That audits a key at zero cost.
- No answer at all is reported as `UNREACHABLE`, which says nothing about the key — claiming otherwise
  would be the easiest lie to tell and the most expensive to believe.
- Where the only documented call would *send data* to the vendor (Browser Use's feedback endpoint) or
  no endpoint is documented at all (Tinyfish), the status is `NO-PROBE`. Untested is not broken, and it
  is not "live" either.

## Worked example — the Keep note, 2026-11-23

The user kept 21 credentials in a Google Keep note, read them out in a chat so they could be wired in,
then deleted the note. The audit is what makes the consequence visible:

```
15 LIVE    still valid at the provider — deleting a note is not revoking a key
 2 DEAD    401 from OpenAI (one of two project keys) and the classic GitHub PAT
 2 UNREACHABLE   Kortix: this device cannot reach the API
 2 NO-PROBE      Browser Use, Tinyfish
```

The lesson is not "don't keep a note". It is that **the deletion felt like the cleanup and was not one**:
the credentials that were pasted into a transcript were still open afterwards, and the only thing that
had been destroyed was the convenient list. Re-running this audit after rotating is what turns a
rotation from an intention into a fact.

## Using the tools

```bash
python3 tools/audit-keys.py          # reads $ZEN_AGENT_KEYSTORE (default /workspace/secrets/api-keys.env)
bash    tools/list-keys.sh           # names + status, never values
bash    tools/show-key.sh NAME       # prints one value, on purpose
```
