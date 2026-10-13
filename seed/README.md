# Seed document

## Why

The copilot's corpus starts empty for every new visitor, so the first question
returns "I couldn't find any relevant documents to answer your question." That
is the worst possible first impression for someone evaluating the project.

The application ingests a default profile document on a visitor's first
session, through **the same PDF pipeline a visitor's own upload uses** — so the
seed also proves the ingest path works rather than bypassing it. Once a visitor
uploads their own PDF, the seed is removed so their document stands alone.

The seed is scoped to the visitor's own `owner_id`, exactly like any upload.
It does not create a shared corpus and does not weaken the per-user isolation
added in `feat: scope documents to the uploading user via OIDC`.

## Files

| File | Role |
|---|---|
| `seed/profile-source.md` | **Source of truth.** The document's text. |
| `seed/profile.pdf` | Generated artefact, committed so the app needs no build step. |
| `scripts/build_seed_pdf.py` | Renders the markdown above into the PDF. |

## Regenerating after an edit

```bash
python3 scripts/build_seed_pdf.py
git add seed/profile.pdf
```

## Sourcing rule

Every claim in `profile-source.md` comes from the candidate's primary files:

- `cv.md` — Akin Gungor — CV Library
- `article-digest.md` — Enterprise Knowledge & Support Copilot

Do not add a claim here that is not in those files. **If a metric changes in
`cv.md`, change it here in the same pass**, or the copilot will confidently
quote a stale figure to a recruiter.

## What it does not claim

No traction, no usage figures, no stars or forks. The deployment is verified
live and the repository is public, and that is exactly what is claimed — a
shipped working build, not a project with adoption.