# Agent workflow diagrams

Visual companion to [discoveries.md](discoveries.md). Proposed workflow, not in use yet.
Branch model: `develop` integrates batches; `main` is the safe branch users install from.

## 1. Life of a change

```mermaid
flowchart TD
    A["Intent / issue"] --> B["Agent writes change<br/>on type/slug branch"]
    B --> C["Verify before PR<br/>ruff · pytest · makemigrations --check<br/>migrate fwd → back → fwd<br/>verifier subagent · /code-review · /security-review"]
    C -->|fails| B
    C --> D["Open PR<br/>Lane · Tier · Prompted by · Clinical impact · How to revert"]
    D --> E["Required CI<br/>tests on Postgres · MS SQL · MySQL · docs build<br/>+ install/upgrade jobs when that surface is touched"]
    D --> F["AI review (REVIEW.md)<br/>Deep for tier 2"]
    D --> G["Security review"]
    E --> H{"All green and<br/>every thread resolved?"}
    F --> H
    G --> H
    H -->|no, round ≤ 3| B
    H -->|no, round > 3| X["Human rethinks the approach"]
    H -->|yes| I["Human approval by tier"]
    I --> J{"Lane"}
    J -->|standard| K["Squash into batch/*"]
    J -->|trivial · revert · standard alone| L["Squash into develop"]
    K --> M["Combined manual test pass<br/>on a test instance"]
    M -->|a PR fails| R["Revert that PR inside the batch"]
    R --> M
    M -->|passes| N["Batch PR: merge commit into develop"]
    N --> T["develop deployed to shared test instance"]
    L --> T
    T --> O["rc tag on develop → full matrix CI<br/>pilot clinics soak and run the upgrade guide"]
    O -->|problem| P["Fix or revert on develop → next rc"]
    P --> O
    O -->|clean| Q["promotion PR: promote/vX.Y.Z → main<br/>tree must equal the rc"]
    Q --> Z["Tag vX.Y.Z on main<br/>publish the rc artifacts unchanged"]
```

## 2. Branches: develop, main, batches, hotfix and backport

```mermaid
gitGraph
    commit id: "4.1 release" tag: "v4.1.0"
    branch develop
    branch releases/4.1
    checkout develop
    commit id: "PR#4 trivial"
    branch batch/2026-11-03-a
    checkout batch/2026-11-03-a
    commit id: "PR#1 squash"
    commit id: "PR#2 squash"
    commit id: "PR#3 squash"
    commit id: "revert PR#2" type: REVERSE
    checkout develop
    merge batch/2026-11-03-a id: "Batch a" tag: "v4.2.0-rc.1"
    checkout main
    merge develop id: "promote 4.2.0" tag: "v4.2.0"
    branch hotfix/qc-rounding
    checkout hotfix/qc-rounding
    commit id: "PR#5 fix"
    checkout main
    merge hotfix/qc-rounding id: "hotfix" tag: "v4.2.1"
    checkout develop
    merge main id: "back-merge"
    checkout releases/4.1
    cherry-pick id: "PR#5 fix" tag: "v4.1.1"
```

- Only `promotion`, `hotfix` and `revert` PRs reach `main`; every commit on
  `main` carries a release tag.
- The promotion's tree must equal the `rc` tree, so clinics get exactly what
  the pilots tested.
- A hotfix on `main` is back-merged into `develop` the same day; CI on
  `develop` stays red until `main` is an ancestor of it again.
- `git revert -m 1 <Batch a>` undoes a whole batch on `develop`;
  `git revert <PR#1 squash>` undoes one member.
- `releases/4.1` starts from the `v4.1.0` tag and only takes `cherry-pick -x`
  of commits already on `main`.

## 3. Which risk tier?

```mermaid
flowchart TD
    S["Changed paths"] --> A{"Install / upgrade / operate surface?<br/>deploy/ · docs/install/ · settings.py · deps<br/>upgrade commands · migrations"}
    A -->|yes| T2["Tier 2<br/>2 humans incl. install owner<br/>+ install/upgrade/backup CI"]
    A -->|no| B{"QC result logic, auth, API contract,<br/>.github/, data export/delete?"}
    B -->|yes| T2b["Tier 2<br/>2 humans incl. domain owner"]
    B -->|no| C{"Only docs (not install), .po,<br/>or test-only additions?"}
    C -->|yes| T0["Tier 0<br/>no human once checks clean<br/>(clean-slate only; AGENTS.md needs 1)"]
    C -->|no| T1["Tier 1<br/>1 human (can be the prompter)"]
    T0 --> U{"Outside author, model field,<br/>calculation or new dependency?"}
    T1 --> U
    U -->|yes| UP["Go up one tier"]
```

## 4. Review loop with a round cap

```mermaid
sequenceDiagram
    participant A as Author agent
    participant R as AI reviewer
    participant H as Human (prompter)
    A->>R: Push (round 1, full diff)
    R-->>A: Findings tagged Important / Nit / Pre-existing
    A->>A: Fix the whole bug class or resolve with reason
    A->>R: Push (round 2)
    R-->>A: Re-review of new commits only, no repeats
    alt clean
        R-->>H: Summary: "0 Important"
        H->>H: Read evidence, approve this commit
    else still findings after round 3
        R-->>H: Stop and ask to reconsider the approach
    end
```

## 5. Rollback ladder (fastest safe first)

```mermaid
flowchart TD
    P["Problem found"] --> F{"Behind a<br/>runtime flag?"}
    F -->|yes| F1["Admin turns flag off<br/>seconds"]
    F -->|no| W{"Where is it?"}
    W -->|unmerged batch| B1["Revert PR inside batch<br/>or close the batch"]
    W -->|develop only| R1["revert PR on develop<br/>(-m 1 for a whole batch)"]
    W -->|released on main| R2["Clinics reinstall previous tag<br/>restore backup if migrations ran"]
    R2 --> R3["revert or hotfix PR into main<br/>→ patch tag → back-merge to develop"]
    R3 --> R4["Backport to releases/X.Y if needed"]
    R1 --> E["Add an eval case<br/>and a REVIEW.md rule if missed"]
    R4 --> E
    B1 --> E
```
