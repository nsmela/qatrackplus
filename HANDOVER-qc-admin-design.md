# Handover: QC admin page redesign

Written 2026-11-19, updated the same day after merging. Steps 1–4 are built and
all on this branch: step 1 directly, steps 2–4 merged from six agent branches.
The whole non-Selenium suite passes and every page has been looked at in a
browser (see [Checked after merging](#checked-after-merging)). Nothing has been
reviewed by a person or pushed. Remove this file, the agent brief
(`HANDOVER-qc-admin-agent-brief.md`) and `TODO-qc-admin-design.md` before the
branch is merged.

## What this is

Every page in the **QC** section of the Django admin is being restyled to match
the Test and Test List pages built on `feat/test-builder`. Each page also gets
new features. The per-page spec is in
[TODO-qc-admin-design.md](TODO-qc-admin-design.md), which is the source of truth
for scope.

Decisions made by the maintainer:

- **Design source:** `docs/developer/design_system.ai.md` on
  `origin/feature/design-system`. For new text, use the passing (A11Y) shades, as
  the Test List page does.
- **Restyle and add new features**, not restyle only.
- **Build on `feat/test-builder`**, not `feature/htmx`.
- **Implement in parallel** wherever the work allows it.

## Where it is

| | |
|---|---|
| Branch | `claude/qc-view-design-updates-14aeb6` (not pushed) |
| Worktree | `.claude/worktrees/qc-view-design-updates-14aeb6` |
| Base | `origin/feat/test-builder` @ `9fcb7918`. The local `feat/test-builder` is 65 commits behind origin; don't use it. |
| Step 1 commit | `c3a9216f` "Give every QC admin page the Test List page's card layout" |

## Done: step 1, the shared QC template (`c3a9216f`)

Django looks up `admin/qa/<model>/change_form.html`, then
`admin/qa/change_form.html`, then the global one. So a QC-wide template restyles
every QC model that has no override of its own.

- `qatrack/templates/admin/qa/change_form.html`:
  - A pinned title row with the page's one save button group: History, Delete,
    Cancel, Save as New, Save and Continue Editing, Save.
  - Each fieldset is a card, drawn by `admin/qa/includes/qc_fieldset_card.html`.
  - Each inline is a card; the attachments inline uses the shared attachments
    card.
  - Blocks for per-model templates: `qc_title`, `qc_header_meta` and
    `qc_header_actions_extra`.
- `qatrack/templates/admin/qa/change_list.html`:
  - A title with an "x of y" count, the object tools as buttons, a results card
    with the search box, and a filter card.
  - Blocks: `qc_list_title`, `qc_results_title` and `qc_results_icon`.
- `qatrack/qa/templates/admin/qa/shared/_qc_assets.html` holds the inlined CSS
  and JS both templates include, and loads Font Awesome, which admin pages don't
  load by default.
- The Test List page's list styles and filter/scroll scripts moved into shared
  partials: `shared/_changelist_css.html`, `shared/_changelist_js.html`
  (`window.qaChangelist`) and `shared/filter.html`. The Test List page includes
  them and looks unchanged.
- `QCAdminDesignMixin` in `qatrack/qa/admin.py` is on all 14 QC admins:
  - It makes list filters start collapsed.
  - It carries the optional `qc_fieldset_icons`, `qc_wide_fields` and
    `qc_inline_icons` settings, read by `qatrack/qa/templatetags/qc_admin.py`.
- Tests are in `qatrack/qa/tests/test_qc_admin_design.py` (11 tests). They
  include smoke tests that open every QC list, add and change page. The
  `qatrack/qa` and `qatrack/qatrack_core` suites pass (1,140 tests). Two
  existing tests were updated because markup moved:
  - `test_round3_R4.py` reads the Test List page's CSS from the file, so it now
    also reads the shared CSS partials that file includes.
  - `test_admin.py:1436` now expects `qc-readonly` instead of Django's
    `readonly` class.
- I checked the Statuses, Tolerances, Test Lists and Test List Cycles pages in a
  running admin, in both light and dark themes.

## Merged: six agent branches (steps 2–4)

Each step 2–4 group was built by an agent, in its own worktree under
`.claude/worktrees/`, on its own branch starting at `c3a9216f`
(`git worktree list | grep qc-admin`). Every agent was given the brief in
[HANDOVER-qc-admin-agent-brief.md](HANDOVER-qc-admin-agent-brief.md). All six
finished and committed. Each reports `ruff` clean, the pre-commit hooks passing,
and the whole `qatrack/qa` suite passing on its own branch (958–980 tests,
Selenium tests excluded). None was checked in a browser; the brief left that to
the lead.

**Merged** into this branch in the order below, each with its own merge commit
(`--no-ff`), all without conflicts: `ff327b0a` (2A), `6d6ea662` (2B), `4c26279b`
(4), `73a0f9b3` (3A), `a258699a` (3B), `3eee7872` (3C). The branches themselves
are unchanged.

| Branch | Commits | New tests | Pages |
|---|---|---|---|
| `qc-admin/2a-status-tolerance` | `e2e36cd6`, `bdd44871` | `test_qc_admin_2a.py` (30) | Statuses, Tolerances, Auto Review Rules / Rule Sets |
| `qc-admin/2b-frequency-category` | `31a27982`, `a58d06ad` | `test_qc_admin_2b.py` (41) | Frequencies, Categories, Autosaves |
| `qc-admin/4-instances-testpacks` | `eda82559`, `2d3b1736`, `ee74ce8f` | `test_qc_admin_4.py` | Test List Instances, Test Instances, test pack import and export |
| `qc-admin/3a-cycles` | `4d3e6e3d`, `ec75bde9` | `test_qc_admin_3a.py` (19) | Test List Cycles |
| `qc-admin/3b-assignments` | `117fe5dc`, `c9a39b60` | `test_qc_admin_3b.py` (38) | Assign Test Lists to Units |
| `qc-admin/3c-refs-tols` | `a842980e`, `bff71feb`, `3b1991e7` | `test_qc_admin_3c.py` (28) | Set References & Tolerances, copy and set-multiple pages |

### What each branch built (from the agents' reports; see the browser check below)

- **2A, Statuses, Tolerances and Auto Review**
  - Statuses:
    - Cards, with a live status label preview.
    - The list shows each status as a label: border in its colour, black text.
  - Tolerances:
    - Cards by type, with a limits preview that warns when limits are out of
      order. Server validation is unchanged.
    - Inline JS replaces `tolerance_admin.js`, which looked for markup the
      cards don't produce. The old script is no longer loaded.
    - A Used In card counts the Unit Test Infos using the tolerance and links
      to them with `?tolerance__id__exact=`.
  - Auto Review Rule Sets:
    - A checkbox list grouped by result replaces the two-list picker. It posts
      the same rule ids.
    - A Used In card lists the tests that use the set.
- **2B, Frequencies, Categories and Autosaves**
  - Frequencies:
    - Cards, keeping the cal-heatmap preview.
    - A "Next due dates" list (the next 8), refreshed over htmx from
      `admin:qa_frequency_next_due`.
    - A Used In card listing the assignments that use it.
  - Categories:
    - A Used In card on the change page.
    - The tree view gets a QC title row through `change_tree_template`.
    - The grid view uses the shared list.
    - Fixed the `short_name` → `short_description` typo.
  - Autosaves:
    - A summary card with a Recover button.
    - **Behaviour change, approved by the maintainer 2026-11-19:** Recover now builds the link the way the
      Perform QC page's own menu does, adding `&day=` and going through
      `continue_tli` for sessions in progress. Before, it opened the wrong day
      for cycles.
- **4, Test List Instances, Test Instances and test packs**
  - Test List Instances:
    - Cards, and a "View on Site" button for users with `can_view_completed`.
    - The list shows an ID column and a review status label.
    - The delete confirmation page is rebuilt. It lists the service events
      whose status will change, and fixes the breadcrumb.
  - Test Instances:
    - Cards, with status and pass/fail shown as labels.
  - Test packs:
    - Cards on the import and export pages.
    - Fixed raw HTML showing in export descriptions, and the "Test Lists
      Cycles" wording.
  - Docs: `docs/admin/qa/testpack.rst` is partly updated.
- **3A, Test List Cycles**
  - A day builder:
    - Server-drawn rows with drag reorder and remove.
    - An htmx "Add Test List" search dialog (`search-test-lists/`,
      `add-row/`).
    - The rows still save through the inline formset.
  - The ace editors span the card.
  - A Used In card lists the cycle's assignments.
  - The list shows days, a test list summary and assignment counts, with a
    test that the query count stays flat.
  - `m2m_drag_admin.js` and `DynamicRawIDMixin` are retired for cycles.
- **3B, Assign Test Lists to Units**
  - Its own change form replaces the `treenav` template, which is unchanged.
  - Cards: What, Where & When and Who, plus a Contents preview card.
  - An htmx search picker (`search-collections/`, `contents-preview/`)
    replaces `updatecombo`. With JS off, the plain field still works.
  - On a saved assignment, unit and test list show read-only, with an option to
    pick others for Save as New.
  - The admin uses a new `UnitTestCollectionAdminForm` subclass;
    `UnitTestCollectionForm` and the builder's dialog are unchanged.
  - select2 and jQuery UI are no longer loaded.
  - Docs: `docs/admin/qa/assign_to_unit.rst` is updated.
- **3C, Set References & Tolerances**
  - The list's change-list template moved to the project folder.
  - "Not set" / "Not used" come from the builder's `machine_limit_usage`.
  - A pencil on each row opens the builder's existing ref/tol dialog
    (`admin:qa_testlist_machine_ref_tol`; its New Tolerance dialog stacks on
    top). The row updates in place.
  - Change form cards: Details as a description list, Reference & Tolerance,
    and History.
  - The copy and set-multiple pages are restyled.
  - `views/admin.py`'s `CopyReferencesTolerancesView` now adds the admin page
    context (4 lines).
  - Changed one existing assertion, `test_admin.py:1436`, to
    `<dd class="qcr-value">Yes</dd>`.

### Bugs the agents fixed in existing code

- Assignment change page, view-only user: crashed with a 500 (KeyError in
  `UnitTestCollectionForm.__init__`). Fixed in 3B.
- Unit Test Info change page, view-only user: crashed with a 500. Fixed in 3C.
- Copy References & Tolerances: **Cancel on the confirm step actually copied.**
  Fixed in 3C; Cancel is now a link, with a "Change Selection" button.
- Test List Instance delete page: broken breadcrumb link. Fixed in 4.

### Found but not fixed (decide or file)

- **Security, already in the code:** `admin_media/js/testpack-import.js` adds
  rows with DataTables `row.add()`, which renders descriptions from an uploaded
  test pack file as HTML. A crafted test pack can run script on the import
  page. Fixing it means changing a static JS file, so it needs a collectstatic.
- **Data risk, already in the code:** the Autosave `data` field shows as Python
  text, because `qatrack_core.fields.JSONField` has no form field. Saving that
  admin page unchanged would store plain text, and the autosave could no longer
  be recovered. Making `data` read-only would prevent it.
- **The "set multiple references & tolerances" action can't be reached:** it
  isn't in `actions`. 3C repaired its template and context but didn't register
  it, because its save ignores the comment and writes no history.
- Copying references and tolerances (`copy_references`, `.update()`) writes no
  history entries.
- `CopyReferencesAndTolerances` (a FormPreview in `views/admin.py`) is dead
  code: no URL points to it.

### Changes the agents suggested to the shared step 1 files: applied

Applied in one commit after merging:

- `includes/qc_fieldset_card.html`:
  - No more `<label for="">`. A split date-and-time label points at the date
    input (`<id>_0`). A checkbox list's label has no `for`, as on Django's own
    admin forms. (`qc_admin.qc_label_for`)
  - A label that would only repeat its card's title (one field, same name as
    the card, e.g. Comments in the Comments card) is hidden visually but kept
    for screen readers. A required field keeps its label so its `*` still shows.
    (`qc_admin.qc_hide_label`)
  - **Not done:** "Not set" instead of "Not specified". The shared card never
    shows a reference or tolerance; the Set References & Tolerances pages have
    their own templates and already say "Not set". "Not specified" stays for
    other empty read-only fields.
- **Double top border on lists without filters:** confirmed in the browser
  (3px + 3px). Fixed in `_changelist_css.html`; the results head inside an
  unfiltered `#changelist` no longer draws its own.
- **Dialog CSS in one place:**
  - `shared/_modal_css.html` has the dialog frame: backdrop, dialog, header,
    body, fields, footer and buttons.
  - `shared/_reftol_dialog_css.html` has the Reference and Tolerance and New
    Tolerance dialogs, plus the error and alert lines the Assign dialog shares.
  - Both were moved unchanged out of `testlist_assets.html`. The Test List
    builder, the Test List Cycle page and the Set References & Tolerances page
    include them. The cycle and references pages keep only a few lines of their
    own: the references page needs its inputs pinned by id, because there the
    dialog sits outside `#content-main`.
  - Checked by comparing every dialog element's computed styles before and
    after, on all three pages: no change beyond sub-pixel rounding.

## Checked after merging

**Automated:** `uv run ruff check .` passes, `manage.py check` finds no issues,
and the whole suite passes: `uv run pytest -m "not selenium"` gave 2154 passed,
5 skipped, 38 deselected. `qatrack/qa` + `qatrack/qatrack_core` gave 1321 passed
after the last merge.

**In a browser** (dev server, sqlite, a little demo data; Chromium in the
desktop app's browser pane). No console errors, and no 4xx or 5xx responses in
the server log.

- **Tolerances:** choosing a type shows the right card. The limits preview
  updates as you type and warns when limits are out of order. Saving out-of-order
  limits shows the server error on the field.
- **Frequencies:** the recurrence widget, the cal-heatmap preview, Next Due
  Dates (refreshes when the due window changes) and the Used In card all work.
- **Auto Review Rule Sets:** the checkbox list shows rules grouped by result,
  each with its status label. The Used In card shows.
- **Statuses:** the list shows each status as a coloured label with its word.
- **Test List Cycles:** day rows, the Add Test List dialog (search, "Already in
  this cycle", Add), removing a day and adding it back, then Save and Continue
  all work. The rows come back in order. Drag and drop was not tried.
- **Assignments:** the picker (choosing Test List or Test List Cycle, searching,
  Choose) and the Contents preview card (a cycle's days, or a test list's tests)
  work. The change page shows the unit and test list read-only.
- **Set References & Tolerances:** the list shows "Not set" / "Not used". The
  pencil opens the dialog. New Tolerance stacks on top and, once created, is
  selected in the dialog. Saving updates the row in place and shows a "Saved"
  message.
- **Categories, Autosaves, Test List Instances:** lists and the TLI change page
  render.
- **Dark theme:** the lists, the cycle page and the TLI page keep white cards
  with readable text.
- **About 768px wide:** the cycle page, the assignment page and the Unit Test
  Info list stack into one column with nothing cut off. Header buttons wrap to a
  second row.

Small things noticed: fixed in the second session (see below), except one:
the Autosave change page marks **Work completed** as required, though an
autosave in progress has none, so saving that page as it stands fails
validation (`null=True` without `blank=True`; already so on `feat/test-builder`). That sits with the Autosave `data` question under
[Found but not fixed](#found-but-not-fixed-decide-or-file).

## Second session (2026-11-19)

Picked up from the handover above. Committed as one commit on this branch.

**Small fixes:**

- **Add Tolerance with no type chosen:** neither value card shows (unless it
  already has values or errors), and a hint under Type says "Choose a type to
  set its limits or choices." Before, both cards showed.
- **Field errors** now sit under their input, not above it, so an input with an
  error stays level with the others in its row
  (`includes/qc_fieldset_card.html`, `_qc_assets.html`).
- **Assignment page title:** "Add / Edit / View Test List Assignment" instead of
  "Edit Unit test collection". Done in the template; changing the model's
  verbose name would need a migration.
- **Cycle search:** `hx-trigger` is now `input changed`, so pasting with the
  mouse searches. The assignment picker already used `input`.

**Docs** (`docs/admin/qa/`):

- `test_list_cycles.rst`: the raw-ID picker section is rewritten for the day
  builder (Add Test List dialog, drag to reorder, the bin icon, Used In). The
  old screenshots it referenced are no longer used; the image files are still
  there.
- `setting_refs_and_tols.rst`: the list's pencil, what "Not set" / "Not used"
  mean, and the copy page's Preview / Change Selection / Cancel buttons.
- `tolerances.rst`, `auto_review.rst`, `frequencies.rst`: a short paragraph
  each on the limits preview, the rule checkbox list and Next Due Dates, and
  their Used In cards. Fixed "Frequencis" and "chossing".
- `testpack.rst`: the direct URLs were wrong (on master too). They are
  `/admin/qa/testlist/export-testpack/` and `/admin/qa/testlist/import-testpack/`.

**Checked in a browser** (port 8019, same sqlite db):

- Add Tolerance: no cards until a type is picked; the right card for each type;
  a card with values stays when the type is cleared; an out-of-order save shows
  the error under Tolerance Low with the four inputs level.
- Test List Cycle: **drag and drop** reorders the rows and renumbers the days;
  Save and Continue keeps the new order. Put back afterwards. A pasted search in
  Add Test List filters at once.
- Assignment page: the new title.
- **Test pack export and import:** export (all test lists and cycles) returns a
  `.tpk`; importing it lists everything and reports "2/2 testlists's, 1/1
  testlistcycles's were imported". Import makes `-1` copies of items that
  already exist, as on master. The copies were deleted from the dev db again.
- **Autosave Recover:** with a demo autosave on day 2 of the cycle, Recover
  opens `perform/2/?autosave_id=1&day=2`, which shows Weekly Output (day 2) with
  the autosave loaded. Perform QC 404s unless the user is in one of the
  assignment's Visible To groups; that's existing behaviour.
- No server errors.

Still not tried by hand: Save as New, Delete and a view-only user (the tests
cover them on every page).

**Behaviour change, approved by the maintainer 2026-11-19:** the cycle's Add Test List dialog won't add a
test list that is already in the cycle ("Already in this cycle"). The old
raw-ID picker allowed it. A test list twice in one cycle already breaks the
membership's natural key (test list + cycle slugs, used by test packs), so this
looks right, but a clinic with a repeating A/B/A/B cycle built that way can no
longer build one. Existing cycles still show and save.

**Translations: catalogues updated, not translated.** GNU gettext 1.0 is now
installed (winget `mlocati.GetText`, in
`%LOCALAPPDATA%\Programs\gettext-iconv\bin`, on the user PATH). `makemessages`
ran for fr, fr_CA and es, for both `django` and `djangojs`, then
`compilemessages`. It's in its own commit so it can be dropped and re-run if
`feat/test-builder` runs its own first.

- On Windows `makemessages` writes references as `.\qatrack\x.py`. They were
  rewritten to `qatrack/x.py` and re-wrapped with `msgcat`, to match the
  existing files. Most of the remaining `.po` diff is line numbers that moved.
- The new strings (from this branch and `feat/test-builder`) are untranslated.
  `msgmerge` added a fuzzy guess to some of them. Fuzzy entries aren't compiled,
  so they show in English until a translator confirms them.
- `django.po` counts (translated / fuzzy / untranslated): fr 2019 / 246 / 313,
  fr_CA 2016 / 249 / 313, es 1132 / 735 / 711.
- French has 32 fewer translated entries than before, because their English
  text changed or was removed (typo fixes, reworded or deleted strings on
  `feat/test-builder`). They were already not showing, since `.mo` lookups use
  the exact English text. Each was checked: none is still used in the code.
  Their old translations are kept as fuzzy suggestions or `#~` entries.
- `test_translation_catalogues.py` and the full non-Selenium suite pass
  (2161 passed, 5 skipped).

## Next steps

1. **Read every diff.** `AGENTS.md` requires a human to read and understand each
   line before a PR is opened. Including the merge commits, `git diff
   origin/feat/test-builder...HEAD` shows everything this branch adds.
2. ~~Merge into this branch.~~ Done; see above.
3. ~~Apply the shared-file suggestions.~~ Done; see above.
4. **Translations:** catalogues updated and compiled (see
   [Second session](#second-session-2026-11-19)). Still to do: translate the new
   and fuzzy entries, ideally by the French translator, then run
   `uv run python manage.py compilemessages` again. Never hand-edit the `.mo`
   files.
5. **Check every QC page by eye,** in light and dark themes, at desktop width and
   at about 768px:
   - Save, Save and Continue, Save as New and Delete.
   - Validation errors.
   - A view-only user.
   - Each new feature listed above.

   Most of this has now been done; see [Checked after merging](#checked-after-merging)
   for what hasn't.
6. ~~Docs.~~ Done in the second session. Still to do: new screenshots for
   `test_list_cycles.rst`, `assign_to_unit.rst`, `testpack.rst` and
   `setting_refs_and_tols.rst`.
7. Run `uv run ruff check .` and `uv run pre-commit run --all-files`.
8. **Open questions for the maintainer:**
   - ~~Approve the Autosave Recover link change?~~ Approved 2026-11-19.
   - ~~Approve the cycle picker refusing a test list that's already in the cycle?~~
     Approved 2026-11-19.
   - Register the set-multiple action?
   - What to do about the test pack import script and the Autosave `data`
     field?
   - ~~Which branch should the PR target?~~ Decided 2026-11-19:
     **`feature/htmx` on `nsmela/qatrackplus`** (`origin`). This branch sits on
     `feat/test-builder` (at `9fcb7918`), which isn't in `feature/htmx` yet, so
     a PR opened now would carry 117 commits: 90 from test-builder and 27 of this
     branch's own. The maintainer will squash-merge it later, so one combined
     PR is fine; there's no need to land test-builder first. Note that `origin/feat/test-builder` has moved 53
     commits on since (it merged `develop`), so this branch may need those
     merged in too.
   - Should the branch be pushed?
9. Once merged, remove the agent worktrees:
   `git worktree remove .claude/worktrees/agent-<id>` for each `qc-admin/*`
   worktree. They are locked, so unlock them first.

## Local environment (this worktree)

- `qatrack/local_settings.py` and `local_test_settings.py` are gitignored
  copies from the `qatrack-test-builder-r12-b19abd` worktree. Both use sqlite at
  `db/default.db`.
- `db/default.db` is migrated, has the default fixtures loaded and has a local
  superuser for the dev server. If you need to log in, set its password with
  `uv run python manage.py changepassword admin`. It has a little demo QC data:
  unit "Linac 1", test lists "Daily Linac QC" and "Weekly Output", the cycle
  "Monday/Tuesday cycle", two assignments, one Test List Instance, two auto
  review rules and one rule set.
- `.claude/launch.json` defines the `qc-admin-dev` dev server on port 8017. It
  is not committed.
- Agents' worktrees each need the two settings files copied in and their own
  `uv sync --dev`.

## Gotchas found on the way

- `runserver --noreload` keeps rendering cached templates, so template edits
  don't show up. Use the normal reloader.
- Admin pages don't load Font Awesome, so icons show as empty boxes unless a
  page loads it. `_qc_assets.html` does.
- On the Test List Cycle page, the generic layout leaves the ace editors
  (description and JavaScript) at half width. 3A owns fixing that.
- Ruff's `UP038` rule wants `X | Y` in `isinstance`. The pre-commit ruff hook
  enforces it.
- The CRLF warnings on commit are harmless (`core.autocrlf`).
- Lessons carried over from `feat/test-builder`, and repeated in the brief:
  - No new static files: production runs `DEBUG=False` without collecting new
    static.
  - Put templates in `qatrack/templates/admin/qa/…`, which is searched before
    the app folders.
  - Scope CSS to `#content-main`.
  - Pin colours on white cards so they stay readable in the dark theme.
