# Review instructions

Read by Claude Code Review from the base branch, never from the PR itself.
Changes here take effect after they merge. This file guides the automated
reviewer only. It does not replace the human review that `AGENTS.md` requires.

QATrack+ records radiotherapy and imaging QC results that clinics act on, and
each clinic installs and upgrades it themselves. Here, failure means one of two
things: a clinic is shown a wrong QC result, or a clinic can't install, upgrade
or roll back.

## What Important means here
Use Important only for findings that would:
- **Change a QC result or schedule without saying so:** pass, tolerance or
  action status, references, tolerances, composite or calculated values, or due
  dates. This covers `Tolerance`/`Reference` and `calculate_pass_fail` in
  `qatrack/qa/models.py`, `CompositeCalculation` in `qatrack/qa/views/perform.py`,
  and the client-side logic in `qatrack/qa/static/qa/js/qa.js`. When the
  server-side and client-side logic disagree, that is Important.
- **Break an install, upgrade or rollback** (see "Install and upgrade surface").
- **Lose or corrupt existing data:** a destructive migration, a `RunPython`
  without `reverse_code`, a dropped or renamed column that the previous release
  still reads, or a delete without a confirmation or permission check.
- **Weaken a permission or auth check, or leak data:** credentials, tokens,
  patient-identifying data, or physicist or unit details in logs, errors or API
  responses.
- **Break a database backend:** an ORM feature, raw SQL or migration operation
  that doesn't work on PostgreSQL, MS SQL Server or MySQL.
- **Weaken, skip or delete an existing test,** or change an expected QC value in
  a test without explaining why in the PR.

Everything else, including style, naming and refactor ideas, is a Nit at most.

## Install and upgrade surface
Review these paths as high risk, even when the diff is small:
- `deploy/**`: Apache, nginx, supervisor, the Windows `*.ps1` and WinSW
  scripts, Docker, `local_settings.py` templates, `backup.sh` and role SQL.
- `docs/install/**` and the upgrade steps in `release_notes.md`. Here, failure
  means the docs lie: a command, path, version or ordering that no longer
  matches the code.
- `qatrack/settings.py`, `manage.py`, `pyproject.toml`, `uv.lock` and
  `requirements/`.
- Commands that admins run during an upgrade: `backup_site`, `migrate_accel`,
  `convert_to_innodb` and `clearcache`.
- Migrations, especially data migrations.

For these paths, check that:
- A setting added or renamed in `settings.py` has a default, and appears in
  `docs/install/config.rst` and the `deploy/*/local_settings.py` templates.
- A new or bumped dependency installs on Windows with pip, as well as with uv.
  The PR should also say whether it is an LTS release.
- The previous release can still run on the new schema (expand, then contract).
  If it can't, `release_notes.md` must say so and give the backup and restore steps.
- Upgrade steps in the docs come in the order the code needs them, and backing
  up comes first.

## Always check
- A bug-fix PR includes a test that fails without the fix.
- A model change comes with its migration. A migration that the PR adds is
  reversible, or the PR explains why it can't be.
- A user-facing string is wrapped for translation. `.mo` files are only changed
  together with their `.po` source.
- A user-facing change updates `release_notes.md`. A change to behaviour,
  settings, URLs or model fields updates the docs that `AGENTS.md`'s
  "Documentation impact" table maps to the changed path.
- New input from forms, the API or uploads is validated, and the view checks
  permissions.
- On a backport PR (into `releases/*`), the change matches the original commit,
  plus conflict fixes only.
- On a hotfix PR, the change is the smallest one that fixes the incident.
  Flag any cleanup that rides along.
- A PR in a `batch/*` branch doesn't change install or upgrade paths alongside
  unrelated work, and doesn't edit this file.

## Scope and evidence
- Report only issues that the diff introduces or makes worse. Tag older problems
  as Pre-existing.
- When the same defect appears in several places, report it once as a class,
  with every location listed.
- Back every claim about behaviour with a `file:line` citation, not a guess
  from a name.
- On a re-review, look only at the new commits, and don't repeat findings
  you've already posted.

## Cap the nits
Report at most five Nits. Don't comment on spelling variants, because
`AGENTS.md` prefers consistency within a file over any one variant.

## Do not report
- Anything that CI or pre-commit already enforces: ruff, formatting, YAML/TOML
  syntax, `django-check`, debug statements.
- `uv.lock` contents (but do check the dependency change behind them), compiled
  `.mo` files, `fixtures/` bulk data, `south_migrations/`, minified or vendored
  static files.

## Summary
Start the summary with counts, for example "2 Important, 1 Nit". When nothing
needs fixing, say so in one line. Mention it when the PR touches the install
and upgrade surface or the QC result logic, even if you found no issues there.
