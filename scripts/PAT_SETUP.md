# GitHub PAT setup for the daily MLS push

The daily MLS scheduled task uses `scripts/push_to_github.py` to write the 6 refreshed `src/data/<slug>-stats.json` files to GitHub via the Contents API. That triggers a Netlify rebuild without ever touching the local git working tree, sidestepping the stale `.git/index.lock` and missing-credentials problems we hit when running `git push` from inside Cowork.

## What you need
A **fine-grained personal access token** (PAT) on the `Bonesbot/adamson-website` repository with these permissions:

- **Repository access:** Only select repositories → `Bonesbot/adamson-website`
- **Repository permissions:**
  - Contents: **Read and write**
  - Metadata: **Read-only** (auto-selected, can't disable)

That's it. No org permissions, no other repos. Single-purpose, least-privilege.

## How to create it

1. Go to https://github.com/settings/personal-access-tokens/new
2. **Token name:** `adamson-website daily MLS push (BonesBot)` — or whatever you like
3. **Expiration:** 1 year (max). Set a calendar reminder for 11 months out.
4. **Resource owner:** your account (Bonesbot)
5. **Repository access:** Only select repositories → `Bonesbot/adamson-website`
6. **Repository permissions:** scroll to **Contents** → set to **Read and write**
7. Click **Generate token** at the bottom
8. Copy the token (starts with `github_pat_…`). You won't see it again.

## How to install it

Append these lines to the project's `.env` file (`AG_website/.env` — same directory as `package.json`):

```
# GitHub PAT for daily Netlify push (rotate annually)
GITHUB_TOKEN=github_pat_paste_yours_here
GITHUB_REPO=Bonesbot/adamson-website
GITHUB_BRANCH=main
```

`.env` is already in `.gitignore` (verified) so the token won't accidentally get committed.

## How to test it
From the AG_website folder, run:

```
python3 scripts/push_to_github.py --slugs longboat-key,lido-key,siesta-key,downtown-sarasota,st-armands,bird-key --dry-run
```

Expected output: a JSON block with `"status": "dry_run"` and per-slug entries showing whether each file would be `would_push` (changed) or `unchanged`. If you see `"status": "failed"` with `"401 from GitHub"` in `failed_files`, the token is wrong, expired, or missing the Contents:write scope.

## How to rotate it

When the calendar reminder fires (or the daily email starts reporting `auth_failed`):
1. Generate a new token (same steps above)
2. Replace the `GITHUB_TOKEN=…` line in `.env`
3. Optionally revoke the old token at https://github.com/settings/personal-access-tokens

Same process if the token is ever compromised.

## What this replaces

Before: scheduled task tried `git add` → `git commit` → `git push` from inside Cowork. Failed because (a) the Cowork mount disallows file deletes inside `.git/`, leaving stale `index.lock` files; and (b) HTTPS origin had no stored credentials in the sandbox.

After: scheduled task calls `push_to_github.py`, which uses HTTPS + the PAT to PUT each changed file via `https://api.github.com/repos/.../contents/src/data/<slug>-stats.json`. Each PUT is atomic with optimistic SHA locking, retried once on 409. No local git state, no lock files, no credential helper, no SSH keys.

## Permissions diagram (what the token can / can't do)

```
github_pat_… (this token)
├── Bonesbot/adamson-website ─── Contents: read + write ✓
│                                Metadata:  read       ✓
│                                Anything else:        ✗
└── (no other repos, no org access, no user data)
```

If GitHub ever sees suspicious activity it can only affect this one repo's file contents on the `main` branch — not your account, your other repos, or any org you belong to.
