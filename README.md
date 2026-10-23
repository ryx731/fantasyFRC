# Fantasy FRC

FastAPI + SQLite fantasy FRC league application. The existing accounts, league IDs, and draft picks are preserved by an additive startup migration. A legacy SQLite database is automatically backed up beside itself as `*.pre-season-upgrade.bak` before its schema changes. Keep database files and backups private.

## Run

From this project directory:

```powershell
.\.venv\Scripts\python.exe -m uvicorn src.main:app --reload
```

Open http://localhost:8000. Use Python 3.10+ and install `requirements.txt` when creating a new virtual environment. Copy `.env.example` to `.env` and configure a stable `SECRET_KEY`. Without it, sessions expire across restarts. `DATABASE_URL` defaults to `sqlite:///./fantasy_frc.db`. Google sign-in uses `GOOGLE_CLIENT_ID` from the server configuration; the browser no longer has a hard-coded client ID.

## League experience

Administrators sign in through the regular login form. The Admin button opens a server-authorized overview of accounts and leagues. Provision or reset a local administrator with `.\.venv\Scripts\python.exe -m src.manage_admin admin`; enter the password at the prompts. Passwords are hashed with Argon2, and registration cannot grant the admin role. Account provisioning is explicit and never resets a password at startup. League commissioner permissions continue to follow league ownership.

Team appearance options include labeled palette previews and a selected state. Branding references and color adaptations are recorded in `static/THEMES.md`.

- My leagues dashboard; private league membership and persistent league navigation.
- Cryptographically random 12-character invite codes, with commissioner rotation. Database IDs are internal identifiers and cannot be used to join.
- Configurable manager capacity, roster size, starters, regular-season scoring periods, and optional four-manager playoffs.
- Commissioner-started randomized snake draft, exclusive FRC picks, turn enforcement, logged commissioner proxy picks for absent managers, draft board and auto-refresh.
- Named fantasy teams, starter/bench lineups, watchlists, a small starter FRC directory, numeric team entry, availability filters.
- Round-robin matchups, odd-manager byes, finalized standings, semifinal/final advancement, champion display.
- Rolling-priority waiver claims with cancellation and commissioner processing; one-for-one trade offers, acceptance, rejection and cancellation; drops and transaction history.
- League clubhouse messages and activity feed.
- Configurable Standard/Half PPR/Full PPR fantasy templates, rule versioning, season activation, normalized JSON match imports, correction deduplication, per-robot breakdowns, and immutable finals.
- Mobile layouts, labeled controls, keyboard-accessible dialogs, focus styles, six themes, request feedback, and expired-session handling. Core screens have no CDN framework dependency.

## Season operations

Create league → invite friends → start draft → finish all rounds → review scoring and activate → set starters → commissioner opens period → import played-match robot metrics → review breakdowns → finalize → process waivers and trade between periods → open next period.

Opening a period immediately locks every lineup and roster transaction. Start times are commissioner-controlled, not inferred from a calendar. Only frozen starters contribute. A robot with no recorded match scores zero. Finalization requires some played-match data but cannot prove completeness; review missing robots before confirming. Rules freeze at the first open period. Fantasy results reflect commissioner imports, not an automatic live feed.

Season structure is fixed at league creation. Playoffs require four managers before drafting. Regular season ranks by wins + half ties, then points for, then original roster join order. Playoff ties go to the better regular-season seed. Byes do not change W/L/T or points-for totals. A no-playoff season is won by the final standings leader.

## Kickoff integration

Read `KICKOFF.md`. The BIOCORE metric names and weights are provisional examples. There is no fabricated official ruleset, robot ranking, projection, or live scoring. The starter directory is not a complete FRC registry; numeric picks are manually entered and commissioner-verified. Configure an adapter to the released game or scouting provider before importing production data.

## Verify

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
node --check static/app.js
```

Tests use isolated databases and cover permissions, migration, draft order, roster locking, waiver conflicts, trades, scoring, and playoffs. `tests/http_smoke.py` runs a separate temporary HTTP server and database to exercise authentication and the complete league API.

## Layout

`src/models.py`: persistence · `src/migrations.py`: legacy upgrades · `src/routers/leagues.py`: authorized season operations · `src/scoring.py`: season-independent metric scoring · `src/schemas.py`: validated API payloads · `static/`: browser application.

API reference: http://localhost:8000/docs. Every league read requires membership; commissioner actions require ownership. League mutations serialize on the league row to prevent concurrent draft picks, joins, roster additions and trade acceptances from bypassing checks.
