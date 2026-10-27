# Test List Builder: issues for review

Temporary. Written while working through `TODO-test-builder.md`, for the
maintainer to review. Remove before merging.

Every item in `TODO-test-builder.md` is done. No task needed more than three
attempts, so nothing was skipped. Each task was done by an agent with a
written plan, then checked (tests, lint, screenshots) and committed on
`feat/test-builder`. The whole `qatrack/qa` suite passes (551 tests).

## Decisions to review

These are choices made during the work that you may want to change.

### Editing modes and machine values
- **References and tolerances are set in a dialog in machine mode.** It
  uses the Unit Test Info admin form's rules and writes the same change
  history (one shared helper, also used by the admin page). It saves
  straight away, applies to that test on that unit in every list, and
  updates every matching row in place. There's no review step, as on the
  admin page. Needs `change_unittestinfo`; view-only users keep a link to
  the admin page.
  - The reference field starts filled with the current value; leaving it
    unchanged keeps the existing Reference, so history doesn't record a
    false change.
  - "Not set" is highlighted only where it causes "No Tol Set" on Perform
    QC: reference and tolerance for numerical types, reference for Yes/No,
    tolerance for text and multiple-choice types. Text-type references,
    Upload and Date tests show "Not used".
- **New Tolerance dialog** (stacked on the first): only the types that fit
  the test (none for Yes/No), saved through the Tolerance admin's form and
  duplicate check, plus a limit-order check the admin lacks. A duplicate
  offers "Use This One". The tolerance applies to the machine only when the
  first dialog is saved.
- **Shared settings are locked in machine mode.** Details become read-only
  and add/remove/reorder/outline controls are hidden, with a banner saying
  how to get back to the base list.
- **Which units appear:** direct assignments first, then "Through other test
  lists" for units that get the list through a parent list or a cycle. Each
  unit appears once. Needs `view_unittestinfo` or `change_unittestinfo`.
- **The chosen unit stays in the URL** (`?unit=`) and survives Save and
  Continue Editing.
- **Switching units with unsaved changes** asks first; switching reloads the
  page at that unit and drops the changes.
- **Tolerances display as the Unit Test Info admin shows them**, e.g.
  "Percent(-3.00%, -2.00%, 2.00%, 3.00%)". Yes/No references read Yes/No.
- **Type Value column (base list):** Constant shows its value; Multiple
  Choice its choices; Wraparound "low to high"; Composite, String Composite
  and Upload the first line of the calculation (cut at 60 characters, full
  text as a tooltip). Other types show "None".

### Preview
- **Full Perform QC preview only for direct assignments.** It's the real page
  in a frame, read-only: banner, no submit, no autosave, no upload, POST
  refused. Needs `change_testlist`.
  - It changes the real Perform QC template and `qa.js` behind a `preview`
    flag; the normal page is tested unchanged.
  - Composite calculations still call the server, which only calculates.
    Procedures using `UTILS.write_file` create an orphan attachment, as they
    do on Perform QC.
  - It ignores the assignment's visible-to groups and active flag.
  - It shows the last saved version, with a note when there are unsaved
    changes.
- **Base list and "through" units** get the layout preview with a note on
  how to see the full one.
- **Outlined sublists in the layout preview** copy Perform QC's look (grey
  rules above and below, name in italics), not a full box.

### Saving
- **One button group, in the title row**, which stays pinned on wide
  screens. Edit page: History · Delete · Cancel · Save As… · Save and
  Continue Editing · Save. Add page: Cancel · Save and Continue Editing ·
  Save. Django's bottom bar and "Save as new" are gone.
- **Save As…** checks the slug as you type and suggests a free one. If the
  copy fails validation, the page comes back as an add page for the copy and
  never touches the original. The copy opens in Base list mode.
- **Description and Duplicate dialogs save straight away** (they change the
  Test, not the test list), and each dialog says so.
- **Assign to Machine dialog saves straight away** and says so. It uses the
  Unit Test Collection admin form's rules, offers active units only (grouped
  by site), allows two Ad Hoc assignments to one unit as the admin page
  does, and writes an admin history entry.

### Unsaved changes
- **"Changed" means the form's posted values differ from when the page
  loaded**, covering field edits, added/removed/reordered rows, outline
  checkboxes and attachments. After a failed save the page starts as
  changed.
- **In-page dialog** for same-tab links (Cancel, breadcrumbs, History,
  Delete, header and sidebar links); the browser's own prompt covers reload,
  close and back. New-tab links and the Editor/Preview switch don't prompt.

### Layout and look
- **Sticky admin header:** the header and breadcrumbs are one pinned block
  on every admin page (`base_site.html`). A small script measures its height
  into `--qa-admin-top-h`, the only CSS custom property added (the height
  varies from 49 to 158px). Unpinned below 768px wide or 600px tall. The
  Test List title row pins under it except below 1024px wide or 700px tall.
- **List page, 1024px and narrower:** the filter card moves above the
  results, its groups side by side, each capped at 180px tall.
- **Search on the list page is a secondary button**, so "New Test List" is
  the page's one primary action.
- **Test counts:** the Tests & Sublists badge and the page header both count
  all tests, including those inside sublists ("7 tests · 1 sublist").
- **Parent Test List Memberships** sits directly below Tests & Sublists.
- **Header buttons:** Expand All, Add Sublist, Add Test.
- **Neutral colours:** category pills, type badges and sublist cards have
  one neutral style each; amber, per-category and per-type colours are gone.
  Tinted banners became grey with a `#424f57` left rule; errors keep a red
  rule.
- **Meta text on hovered rows is `#555`**, because the spec's `#6e7785`
  drops to about 4.2:1 on the hover colour.
- **Classes renamed to `tlb-`** where they clashed with `base.css`
  (`tl-table`, `tl-form`, `tl-field`).
- **Page titles:** "Test Lists", "Add Test List" and "<name> | Edit Test
  List" instead of Django's "Select test list to change" / "Change test
  list".

### Translation
- **The builder's JS strings live in a `TL_STRINGS` table** rendered by the
  template, because `makemessages -d djangojs` doesn't scan `<script>` blocks
  in `.html` files. New JS strings must be added there.
- **Type badges are translated with the context "test type badge".**

## Open issues: Test List builder

- **"Change" on an existing sublist** swaps in a card built as if the
  sublist were new (empty id, outline unchecked), so its outline setting and
  its pairing with the saved row are lost. Focus also can't return to the
  Change button. Existed before this work.
- **Adding a sublist that repeats a test** already in the list is allowed;
  saving then fails with the duplicate-tests error. Better to warn when
  adding.
- **Duplicate Test copies references and tolerances on every unit** with no
  `change_unittestinfo` check, and the copies share the same Reference
  objects.
- **The description dialog saves with `update_fields=["description"]`**, so
  the Test's `modified`/`modified_by` aren't updated.
- **The Duplicate click handler doesn't check `res.ok`**, so a 403/500 page
  would appear as raw text. Hidden today because the button is hidden
  without permission.
- **A generic click handler hides any clicked dialog backdrop directly**,
  bypassing that dialog's own close logic (focus isn't returned then).
- **A user without delete permission on the inlines** can mark a row removed;
  validation ignores the row but the formset won't delete it. Edge case.
- **Save As in browsers without `requestSubmit`** triggers the browser's
  leave prompt. Old browsers only.
- **Link blue `#3c8dbc` is still 3.67:1** for text links, as the spec has it;
  the spec's proposed `#357da7` is still open. `#767676` on a hovered list
  row is about 4.27:1.
- **Narrow screens:** at about 800px the builder table and the list page's
  results scroll sideways inside their cards.
- **List page:** the filter card (~860px) is taller than a 900px window, so
  the page scrolls a little and the results card's top goes under the pinned
  header. `initResultsScroll` only recalculates on window resize.
- **Stale JS:** `qatrack/admin_media/js/m2m_drag_admin_testlist.js` (changed
  heavily on this branch) isn't loaded by any template; the builder JS is
  inlined in `testlist_assets.html`. Looks safe to delete.
- **Tolerance wording** ("Percent(-3.00%, …)", "M.C.(OK=a:b, …)") reads like
  code; clinical staff may prefer plainer wording.

## Open issues: elsewhere in QATrack+ (existed before this work)

- `Tolerance` doesn't check limit order (`models.py` ~831), so the Tolerance
  admin accepts e.g. Tolerance Low 2 / Tolerance High 1. The builder's New
  Tolerance dialog now checks it.
- `UnitTestInfo.clean` (`models.py` ~1456) checks percent tolerances
  against the existing reference, not the new one, so changing a zero
  reference to non-zero together with a percent tolerance may be rejected.
  Not verified.
- The Unit Test Info admin history shows changes as "current → old"
  (e.g. "Absolute(…) → None"), which reads backwards.
- Model help text spells "seperated" (Tolerance multiple-choice fields).
- Perform QC renders duplicate element ids when a test appears both directly
  and in a sublist (the seeded "Daily Linac QC" has this layout).

- `UnitTestInfoForm.save` (`qa/admin.py`, ~line 212) stores Yes/No
  references with the numerical type, so the Unit Test Info admin and the
  Perform QC Reference column show "1"/"0" instead of Yes/No.
- `PerformQA.set_unit_test_infos` passes an already-formatted "Do not
  treat…" string to `_()`, so it can't be translated.
- `RemovedInDjango50Warning` (filtering by an unsaved instance) from
  `TestForm.clean` (`qa/admin.py`), `qa/signals.py` (`on_test_save`), the
  PerformQA GET path and test helpers.
- `TestListAdmin.actions` lists `export_test_lists`, which isn't defined, so
  the action is dead.
- `qatrack/templates/admin/change_form.html` uses `{{ opts.module_name }}`
  (gone in Django 4), so every admin change form gets `id="_form"`; its
  breadcrumbs show the changelist link only with `has_change_permission`
  (Django 4.2 uses `has_view_permission`).
- `qatrack/templates/admin/change_list.html` never renders Django 4.2's
  "Clear all filters" link.
- `base_site.html`: "Submitting..." is untranslated and uses "...".
- Below 1024px wide, admin pages in general scroll sideways.
- `/admin/password_change/` logs 404s and RequireJS errors for
  `zxcvbn`/`password_strength`.
- `makemigrations --dry-run` lists pending migrations for faults, parts,
  units, attachments, qa, reports and service_log at the commit this work
  started from. Worth checking on `develop`.

## Before merging

- Run `makemessages -l fr -l fr_CA -l es` (django and djangojs domains) and
  `compilemessages`; there are many new and changed strings.
- Remove `TODO-test-builder.md` and this file.
- Per `AGENTS.md`, a person needs to read the full diff, run the tests, and
  own the change before a PR is opened.

## Fixed along the way (for the record)

- Duplicate Test always failed with an IntegrityError (no `created_by`).
- The Duplicate and Description dialogs were inside the main form, so their
  buttons saved the whole test list.
- Validation counted rows removed in the builder, and removed rows came back
  after a validation error; unsaved rows disappeared after a failed save.
- Builder endpoints had no permission checks beyond staff.
- Search used hard-coded `/admin/` URLs (broken under a sub-path).
- The builder's dialogs and the description text weren't keyboard
  accessible.
