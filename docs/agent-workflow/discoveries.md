# Agent workflow for QATrack+ — discoveries

Working notes, not policy. Tracks what we learned while evaluating whether to
port the SoignantRT SDLC/agent workflow (`nsmela/SoignantRT`: `BRANCHING.md`,
`CLAUDE.md`, `.github/workflows/{lane,rollback,release}.yml`,
`scripts/check-lane.sh`) to QATrack+.

## Goals
1. Merge lanes that keep history clean.
2. Batch several agent results so a human tests them together, instead of one
   review/test cycle per PR.
3. A reliable rollback path.

## What SoignantRT does
- Trunk-based: `main` always releasable, squash merges (1 PR = 1 revertable commit).
- `Lane:` line in every PR, checked by `lane.yml`: `standard` (needs approved
  `intent/<date>-<slug>/plan.md`), `trivial`, `revert` (only `git revert`
  commits), `hotfix` (`Incident:`), `backport` (`cherry-pick -x` into `release/*`).
- Releases are immutable tags; rc tag built once, promoted without rebuild.
- Rollback ladder: flag off → redeploy previous tag (`rollback.yml`) → revert PR.
  Migrations must be expand/contract so the previous release runs on the new DB.
- Agents may branch/commit/push/open PRs; never merge, tag, or deploy
  (local guard hook + GitHub rulesets).

## How QATrack+ differs (facts from the repo)
- Not trunk-based. Upstream has `develop` (PR target, per `CONTRIBUTING.md`),
  `master` (releases), and `releases/X.Y` (`releases/4.0`, `releases/3.1`, ...).
  Note the plural `releases/`, not SoignantRT's `release/`.
- `nsmela/qatrackplus` currently has no `releases/*` branches and `master`
  equals upstream `master`; it does carry `develop`.
- `AGENTS.md` AI policy: every non-draft PR needs a human who has read every
  line, can explain it, ran the tests, and takes responsibility. Autonomous
  final PRs get closed. Batching must not bypass this.
- Self-hosted clinical installs (Linux/Postgres, Windows/MS SQL) with
  "predictable upgrade windows" — there is no single production to redeploy.
  Rollback means "a clinic can go back to the previous version", which is
  dominated by Django migrations and DB backups, not by a deploy button.
- CI (`ci.yml`) runs on every branch push; `release.yml` fires on `v*` tags.
  No lane check, no rollback workflow, no merge queue.

## Proposed lanes for QATrack+
Same names as SoignantRT so tooling (`check-lane.sh`) can be reused, plus one new lane:

| Lane | Target | Requires |
| :-- | :-- | :-- |
| `trivial` | `develop` | Typos, copy, translations-only, patch bumps |
| `standard` | `batch/<date>-<slug>` or `develop` | `Intent:` → approved `plan.md` |
| `batch` (new) | `develop` | Head is `batch/*`; lists member PRs; human batch-test checklist ticked |
| `revert` | `develop` or `batch/*` | Only `git revert` commits |
| `hotfix` | `develop` (then backport) | `Incident:` line |
| `backport` | `releases/X.Y` | `cherry-pick -x` from `develop`/`master`; `Backport-of: #N` |

## Batch lane (the main new idea)
```
develop ──●───────────────────────────●  (merge commit: "Batch 2026-10-24-a")
           \                         /
batch/2026-10-24-a ──●(PR#1)──●(PR#2)──●(PR#3)
                     squash    squash   squash
```
1. Human (or a script) cuts `batch/<date>-<slug>` from `develop`.
2. Agents open PRs into the batch branch; each is squash-merged there after its
   own CI is green. The per-diff "human has read every line" rule still applies
   here — batching saves *testing* time, not *reading*.
3. Human deploys the batch branch head to a test instance (docker compose from
   `deploy/`) and runs one combined manual test pass, using a checklist
   generated from the member PRs' test plans.
4. Batch PR into `develop` with `Lane: batch`, merged as a **merge commit**
   (not squash), so each member PR remains one revertable commit inside it.
5. Rules: batch branch lives ≤ 1 week; ≤ ~5 PRs; no two PRs with migrations in
   the same app (avoids migration-graph conflicts / `--merge` migrations);
   rebase never — refresh from `develop` with a merge.

Lane check for `batch`: head ref matches `batch/*`; every non-merge commit on
the branch is a squash of a merged PR whose base was that batch branch
(verifiable via the GitHub API); `makemigrations --check` passes; migration
leaf count per app is 1.

## Rollback options (fastest safe first)
| Scope | How |
| :-- | :-- |
| One PR inside an unmerged batch | `revert` PR into `batch/*` (`git revert <squash-sha>`), retest |
| Whole batch dropped before merge | Close batch PR, delete branch; `develop` untouched |
| One PR after batch merged | `git revert <squash-sha>` on `develop` (`revert` lane) |
| Whole batch after merge | `git revert -m 1 <batch-merge-sha>` (`revert` lane) |
| A released version at a clinic | Restore pre-upgrade DB backup + reinstall previous tag; or `manage.py migrate <app> <prev>` if migrations are reversible |

Rollback prerequisites to enforce in review/CI:
- Every migration reversible (no `RunPython` without `reverse_code`); CI job
  that migrates forward, back to the previous release's leaf, and forward again.
- Expand/contract for schema changes so release N-1 code tolerates release N schema.
- Upgrade docs keep "back up the database first" as step 1.
- Tag `pre-batch/<slug>` (or record the `develop` SHA in the batch PR) before merge,
  giving a named point to compare/revert against. Human-created only.

## Open questions
- Base on `develop` (upstream convention) or adopt trunk on the fork only?
  Upstreaming PRs to `qatrackplus/qatrackplus` must still target `develop`.
- Where does the batch test instance run (local docker vs. shared staging)?
- Does upstream accept a batch PR, or must each member PR be upstreamed separately?
  (Merge-commit batches preserve per-PR commits, so either is possible.)
- Port `intent/` + `plan.md` gating as-is, or only for `standard` changes touching
  models/migrations/permissions?
- Merge queue needs an org-owned repo; `nsmela/qatrackplus` is user-owned, so the
  batch branch doubles as a manual merge queue.

## Next steps (not started)
1. `scripts/check-lane.sh` port with the `batch` lane + `.github/workflows/lane.yml`.
2. Migration reversibility CI job.
3. Batch checklist generator (collect "How to test" sections from member PRs).
4. Guard hook from `SoignantRT/.claude/hooks` adapted to `develop`/`master`/`releases/*`.

## Comparison with the source video
Source: "Claude Codes New REVIEW.md System, What is it?" (Rob Shocks,
https://youtu.be/bls8ZJ_INMQ). The transcript could not be fetched, so this
compares against the video's topic and the official docs
(https://code.claude.com/docs/en/code-review).

- The video covers one piece: `REVIEW.md`, review-only instructions that
  Claude Code Review reads from the base/default branch, never from the PR.
  SoignantRT uses it as one layer inside a larger SDLC (intent → plan → lanes →
  tags → rollback). The batch lane and rollback ladder above are not from the video.
- SoignantRT's `REVIEW.md` defines "Important" (incl. "blocks a rollback"),
  caps nits at 5, skips generated files/lockfiles, and adds lane-specific
  checks (backport = only the original change; hotfix = smallest change).
  `claude-review.yml` is a fallback for plans without Code Review that feeds
  the base branch's `REVIEW.md` to `claude-code-action`.
- QATrack+ has no `REVIEW.md`. A port would add: migration reversibility
  (`RunPython` without `reverse_code` = Important), migrations still runnable on
  MS SQL Server, missing/uncompiled translations, `release_notes.md` updated,
  PR template boxes ticked, ignore `uv.lock` and compiled `.mo` files.
- Fits the QATrack+ AI policy: Code Review is advisory (never approves or
  blocks), and maintainers commit to not using AI as the final review.
- Batch lane interaction: PRs into `batch/*` have the batch branch as base, so
  Code Review would read `REVIEW.md` from the batch branch. A member PR that
  edits `REVIEW.md` would change the rules for later PRs in the same batch.
  Rule: `REVIEW.md` changes go straight to `develop` (`trivial` or `standard`),
  never through a batch.
