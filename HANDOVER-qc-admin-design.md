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
    - **Behaviour change to approve:** Recover now builds the link the way the
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

Small things noticed, not fixed:

- On a field with an error, the error list sits above the input, so that input
  drops below the others in its row (seen on Tolerance's Action High).
- The assignment page title reads "Edit Unit test collection". This is the
  model's verbose name, not new; the list is titled "Assign Test Lists to
  Units".
- With no type chosen on Add Tolerance, both the Limits and Multiple Choice
  cards show until a type is picked.
- Search boxes use `keyup changed`, as the Test List builder does. Pasting with
  the mouse doesn't search until a key is pressed.

Not tried in a browser: drag and drop, Save as New, Delete, a view-only user,
test pack import and export, and the Autosave Recover button (there were no
autosaves). The tests cover Save as New, Delete and view-only for every page.

## Next steps

1. **Read every diff.** `AGENTS.md` requires a human to read and understand each
   line before a PR is opened. Including the merge commits, `git diff
   origin/feat/test-builder...HEAD` shows everything this branch adds.
2. ~~Merge into this branch.~~ Done; see above.
3. ~~Apply the shared-file suggestions.~~ Done; see above.
4. **Translations:** the strings are new. Run `makemessages` for fr, fr-ca and es
   once, translate or leave the entries empty, then run
   `uv run python manage.py compilemessages`. Never hand-edit the `.mo` files.
5. **Check every QC page by eye,** in light and dark themes, at desktop width and
   at about 768px:
   - Save, Save and Continue, Save as New and Delete.
   - Validation errors.
   - A view-only user.
   - Each new feature listed above.

   Most of this has now been done; see [Checked after merging](#checked-after-merging)
   for what hasn't.
6. **Docs:** `docs/admin/qa/test_list_cycles.rst` still describes the old raw-ID
   picker. The screenshots in `assign_to_unit.rst` and `testpack.rst` are out of
   date. Review the rest of `docs/admin/qa/` for these pages too.
7. Run `uv run ruff check .` and `uv run pre-commit run --all-files`.
8. **Open questions for the maintainer:**
   - Approve the Autosave Recover link change?
   - Register the set-multiple action?
   - What to do about the test pack import script and the Autosave `data`
     field?
   - Which branch should the PR target: `feat/test-builder`, or `develop` after
     test-builder lands? `AGENTS.md` says `develop`.
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
