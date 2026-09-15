# Next Move — CLAUDE.md

## What this is

A marketing/contact site for Akos's chess coaching business ("Next Move"). Flask +
SQLite, single service, deployed on Railway. There is no online booking/payment system —
the whole point of the site is to get a visitor to send a message via the contact form;
everything else (schedule, location, price) gets worked out afterward, since Akos doesn't
have a dedicated teaching space yet.

## Content ownership

**Almost everything editable lives in the database, not in code**, and is edited via a
password-gated `/admin` — Akos owns this content, not future Claude sessions. Don't
hand-write marketing copy into templates; if new editable content is needed, add a
`settings` key or a new table + admin form, matching the existing pattern in `app.py`.
Text seeded with `[brackets]` is a placeholder for Akos to replace — leave that convention
alone rather than "improving" the wording, since the whole point was to keep AI-written
content to a minimum and let him write it in his own voice.

## Stack

- Flask + SQLite (`app.py`, single file, no ORM) — same pattern as this user's other small
  Flask/SQLite sites (`chessscenes`, `zoosnap`).
- **Real runtime data, not git-committed.** Unlike `chessscenes` (whose SQLite is fully
  derived from committed CSV/JSON and rebuilt on every boot), this app's database *is* the
  source of truth — packages, testimonials, FAQ, bio text, and inquiries are all written at
  runtime via `/admin`. It must live on a Railway **volume** (`DATA_DIR` env var, mounted at
  `/data` in production) so a deploy doesn't wipe Akos's edits. Never switch this to
  git-committed SQLite.
- `init_db()` runs on every process start and is idempotent (`CREATE TABLE IF NOT EXISTS`,
  seed-only-if-empty) — safe to run against an already-populated database.
- Uploaded profile photo is re-encoded via Pillow (EXIF-transposed, converted to JPEG,
  capped at 900px) and saved as `uploads/profile.jpg`, always overwriting the previous one
  — there's only ever one current coach photo, not a gallery. `photo_version` in `settings`
  is bumped on every upload purely as a cache-busting query param (`?v=`) on the `<img>` tag.

## Data model

- `settings` — a generic key/value table for the site's editable prose (tagline, bio,
  per-track intros, the first-lesson-free line, social links, etc.). Read once per request
  via `get_settings()` and injected into every template as `settings` (`context_processor`
  in `app.py`) — don't re-query it inside templates.
- `packages` / `testimonials` / `faqs` — near-identical repeatable-content tables, each with
  `sort_order` (reordered via the admin's Up/Down buttons, swapping `sort_order` with the
  neighboring row — see `move_item()`) and `active` (soft hide/show, not delete-by-default;
  a real "Remove" button does hard-delete, since none of this content is referenced
  elsewhere the way e.g. `chessscenes`' events reference places).
- `inquiries` — one row per contact-form submission (name, email, free-text message, which
  `track` they came in on: `general`/`adults`/`kids`/`parent_child`). This **is** the site's
  primary call to action — there's no email/SMS notification wired up, so Akos has to check
  `/admin#inquiries` (the tab shows an unread-count badge) rather than being pinged. Worth
  revisiting if he wants a heads-up instead of having to check.

## Pages

- `/` — homepage: hero, the two tracks (adults / kids), packages, bio, testimonials (hidden
  entirely if there are none active — no fake-empty-section filler), FAQ (hidden if none
  active), and the one real contact form on the site.
- `/adults`, `/kids` — track-specific landing pages. Neither has its own contact form; their
  CTAs link to `/?track=<track>#contact` so the homepage form's "This is about" `<select>`
  pre-selects the right value (`default_track` in `home()`) without duplicating the form.
- Packages are shown identically (same `_packages.html` partial) on all three pages, as
  `<details>` accordions — no JS, just native disclosure widgets, styled via `.package`
  classes in `static/style.css`.
- `/admin`, `/admin/login`, `/admin/dashboard` — password-only auth (`ADMIN_PASSWORD` env
  var, Flask session cookie), same trust model as `zoosnap`'s `/admin`/`/judge`: no
  hashing, fine for a single-owner low-stakes site, not something to "upgrade" without being
  asked. `admin_guard()` is checked at the top of every mutating `/admin/...` route.

## Known gaps / next steps

- **No email delivery for inquiries yet.** Akos has to check `/admin` — there's no SMTP
  configured and no address was available when this was built. If he wants a notification,
  the simplest fix is a transactional-email provider (Resend, Postmark) called from
  `contact()` after the DB insert; don't build this speculatively before it's asked for.
- **`nextmovechess.nl` is not yet purchased or wired up.** The Railway-provided
  `.up.railway.app` URL is the real, working site in the meantime. Once the domain exists,
  follow the same custom-domain pattern documented in `zoosnap`'s and
  `chess-library-api`'s CLAUDE.md (add as a Railway custom domain, point DNS via an `ALIAS`/
  `CNAME` at the target Railway gives you).
- **Newsletter is an explicitly deferred v2** (Akos's own idea, not yet requested as a build
  task) — don't add signup capture, an ESP integration, or a `subscribers` table
  speculatively. Wait until it's actually asked for.
- **Parent + child class is a soft/unconfirmed offering**, not a real package yet — it
  deliberately isn't in the `packages` table, only mentioned as a settings-driven note
  (`parent_child_note`) with a "click if interested" CTA. Promote it to a real package once
  Akos has actually run one.

## Local development

```
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
DATA_DIR=./data ADMIN_PASSWORD=devpassword PORT=5400 python3 app.py
```

`DATA_DIR` defaults to `./data` (gitignored) if unset. `ADMIN_PASSWORD` defaults to
`changeme` if unset — never rely on that default anywhere but local testing.

## Deployment

Railway, `web: python3 app.py` (`Procfile`) — deploys from `main`. Needs a volume mounted
wherever `DATA_DIR` points (see "Real runtime data" above) and `ADMIN_PASSWORD` /
`SECRET_KEY` set as env vars, never committed.
