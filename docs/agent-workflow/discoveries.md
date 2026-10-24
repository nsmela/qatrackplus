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

## Comparison with the source material
Video: "Claude Codes New REVIEW.md System, What is it?" (https://youtu.be/bls8ZJ_INMQ).
Its stated main source is "How the Claude Code team does code review"
(https://claude.dev/blog/solving-code-review-at-anthropic/, Oct 15 2026), plus the
Code Review docs, the GA post and the security-review post. Read directly; the
video transcript itself could not be fetched.

### The post's model
Goal: least human time per change with **no rise in reverts or incidents**
(Claude writes ~90% of Claude Code; merged PRs doubled Jun-Sep, revert share fell >40%).
Six layers of checks with rollback under them:
1. Verified before a PR: tests/build/lint run, fresh-context subagent reviews the diff.
2. AI review on every PR (parallel finders, voting verifiers; Important / Nit / Pre-existing).
3. Security review. Open findings from 2 or 3 **block the merge** until fixed or resolved with a reason.
4. Required CI. PR template asks "Testing", "Risk", "How to revert".
5. Human approval scaled by risk: low = 0, medium = 1, high = 2. Tier set by a
   classifier from the change, not the author. Sensitive paths and CI workflows
   always need a person. Only trusted authors get light paths. Bot approval never
   counts as a person's. The person prompting the agent is a required reviewer.
   Approval covers one commit; new untrusted commits need re-approval.
6. Merge queue, flags, internal use first, staged release (latest → stable).
7. (Under all) Fast detection and rollback: flags off without deploy, reverts, on-call,
   incident review asks which layer should have caught it.
Reviewer improvement: past incidents/reverts become a daily eval; noise measured
by how authors responded. Convergence: one PR ran **50+ agent review/fix rounds**
overnight; ~59% of repeat flags were old code. Fixes: cap at 3 rounds then
reconsider the approach, diff-only re-review, flag the bug class, no repeats.
Result: one-round pass 65% → 78%, 5+ rounds 8.9% → 1.5%.

### Mapping
| Post layer | SoignantRT | QATrack+ today | Proposed for QATrack+ |
| :-- | :-- | :-- | :-- |
| 1 Verify before PR | `make verify` + `verifier` subagent required | `AGENTS.md` test commands; none required | Add a verifier subagent; paste test tail in PR |
| 2 AI review | `REVIEW.md` + `claude-review.yml` fallback | None | Add `REVIEW.md`; `/code-review` locally (any plan) |
| 3 Security review | `secrets.yml` only | CodeQL | `/security-review` + security-review Action; branch protection "require conversation resolution" |
| 4 Required CI | `verify`, `lane`, `secrets` | `ci.yml` (not required on fork) | Make `ci` + `lane` required |
| 5 Risk-based approval | Fixed N approvals + CODEOWNERS | Template: maintainer for breaking/feature/migration, else reviewer | Write the tiers down; path-based CODEOWNERS for `migrations/`, `qa/` calc engine, auth, `.github/` |
| 6 Queue/flags/staged | Merge queue (org only), rc tags | Tags; no flags | Batch branch as manual queue; rc tag to a pilot clinic before final |
| 7 Rollback | Rollback workflow, expand/contract | DB backup in upgrade docs | Reversible migrations CI, revert lanes (above) |
| Incident eval | `evals/` + `agent-evals.yml` | None | Seed from past `fix` PRs and reverts |
| Round cap | Not present | Not present | Cap 3 agent review rounds per PR, then human |

### Where QATrack+ must differ
- **Human reading.** The post calls "did a human read the code?" an imprecise
  proxy and lets low-risk changes merge with zero humans. QATrack+ `AGENTS.md`
  requires a human to read every line of every non-draft PR, and maintainers
  will not use AI as the final review. So tier "low = 0 humans" is not
  available; the floor is 1 (the author/prompter). AI review cuts *finding*
  time, not the reading requirement. Changing that is a policy decision for
  the upstream maintainers, not a workflow tweak.
- **Batching vs. the post.** The post does not batch; it relies on small PRs,
  a merge queue and flags. The batch lane fills the merge-queue role on a
  user-owned repo and adds one combined *manual test* pass, which the post
  replaces with internal dogfooding. Keep per-PR approval tied to its own
  commit (post rule) — the batch PR approval does not replace member-PR review.
- **Flags.** QATrack+ has no runtime flag system, so layer 6/7 "flag off" is
  unavailable; rollback leans on revert + reversible migrations + DB backup.
- **Staged release.** No "latest channel"; the analogue is an rc tag run by
  one or two pilot clinics before the final tag.
- **Code Review availability.** Team/Enterprise only, and not offered under
  the HIPAA configuration or BAA. QATrack+ code holds no PHI, but any test
  fixtures or screenshots attached to PRs must stay PHI-free (already a PR
  template box).

### REVIEW.md notes (from the docs)
- Read from the base/default branch, never from the PR. Reviews never block or
  approve; the check run never fails. Blocking comes from branch protection
  requiring resolved threads.
- `@claude review` (write access) re-runs it; Quick / Standard / Deep set per repo.
- Batch lane interaction: PRs into `batch/*` read `REVIEW.md` from the batch
  branch. A member PR editing `REVIEW.md` changes the rules for later PRs in the
  batch, so `REVIEW.md` changes go straight to `develop`, never through a batch.
- Candidate QATrack+ Important items: `RunPython` without `reverse_code`;
  migration unsafe on MS SQL Server; changes to QC calculation/tolerance logic
  without a test; uncompiled or missing translations; `release_notes.md` not
  updated. Skip `uv.lock`, `.mo`, `fixtures/` bulk data.
