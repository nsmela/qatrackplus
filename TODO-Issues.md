# Test List Builder: issues for review

Temporary. Issues found while working through `TODO-test-builder.md`, plus
any task that didn't succeed within three attempts. For the maintainer to
review; remove before merging.

## Tasks that need review

_None yet._

## Decisions made during implementation

- **Perform QC preview (L):**
  - With a machine picked that the list is assigned to directly, Preview
    shows the real Perform QC page in a frame, read-only. It has a banner;
    submit, autosave and upload are off; POST is refused. It needs
    `change_testlist`.
  - Composite calculations still call the server, which only calculates
    (except procedures using `UTILS.write_file`, which create an orphan
    attachment, the same as on Perform QC).
  - It ignores the assignment's visible-to groups and active flag.
  - It shows the last saved version, with a note when the builder has
    unsaved changes.
  - Base list mode and "through" units get the layout preview with a note;
    through units link to the parent list.
  - Changes the real Perform QC template (`testlistinstance_form.html`) and
    `qa.js` behind a `preview` flag; the normal page is unchanged (tested).

- **Assign to Machine dialog (K):**
  - Creates the assignment straight away, and says so.
  - Uses the Unit Test Collection admin form's rules, limited to unit,
    frequency, assigned to, visible to and active.
  - Active units only, grouped by site. "Ad Hoc" = no frequency.
  - Two Ad Hoc assignments to the same unit are allowed, as on the admin
    page.
  - The duplicate error is reworded in plain language.
  - Writes an admin history entry like the admin page does.
  - The new unit is added to the Editing dropdown without a reload.

- **Unsaved changes (I):**
  - "Changed" means the form's posted values differ from when the page
    loaded, which covers field edits, added/removed/reordered rows, outline
    checkboxes and attachments. Adding then removing an attachment counts as
    unchanged.
  - After a failed save the page starts as changed.
  - In-page dialog ("Stay on This Page" / "Leave Without Saving") for
    same-tab links: Cancel, breadcrumbs, History, Delete, header and sidebar
    links. The browser's own prompt covers reload, close and back.
  - New-tab links and the Editor/Preview switch don't prompt, since nothing
    is lost.
  - Switching the machine dropdown with changes asks first. Switching
    reloads the page at that unit and drops the changes; Stay puts the
    dropdown back.

- **Sticky admin header (H):**
  - The admin header and breadcrumbs are wrapped in one pinned block on every
    admin page (`base_site.html`). A small script measures its height into
    `--qa-admin-top-h`, the one CSS custom property added, because the height
    varies (49–158px).
  - Unpinned below 768px wide or 600px tall.
  - The Test List title row and its buttons pin under it, except below 1024px
    wide or 700px tall, where both together would take over a quarter of the
    screen.
  - Django's `#container` `height:100%` was overridden; it made the header
    unpin about a screen down on long pages.

- **One save button group (F):** it's in the title row and Django's bottom
  bar is gone. Edit page: History · Delete · Cancel · Save As… · Save and
  Continue Editing · Save. Add page: Cancel · Save and Continue Editing ·
  Save. "Save Test List" is now "Save". Delete is ghost style.
- **Save As (F):**
  - Checks the slug as you type and suggests a free one (`-2`, `-3`, …).
  - If the copy fails validation, the page comes back as an add page for the
    copy, never touching the original.
  - The copy always opens in Base list mode.

- **Machine mode (J):**
  - Picking a unit in the Editing dropdown shows that unit's references and
    tolerances (direct tests and sublist tests) in place of Type Value.
  - They're read-only in the builder. A pencil on each row opens that
    unit's existing Unit Test Info admin page in a new tab, which already
    handles reference/tolerance history and review.
  - Shared settings are locked in machine mode: details become read-only and
    add/remove/reorder/outline controls are hidden. A banner explains how to
    get back to the base list.
  - The dropdown lists direct assignments first, then a "Through other test
    lists" group for units that get this list through a parent list or a
    cycle. Each unit appears once.
  - The chosen unit is kept in the URL (`?unit=`) and survives Save and
    Continue Editing.
  - Needs `view_unittestinfo` or `change_unittestinfo`; without either, only
    "Base list" is offered.
  - Tolerances display as the Unit Test Info admin shows them, e.g.
    "Percent(-3.00%, -2.00%, 2.00%, 3.00%)". Yes/No references read Yes/No.

- **Type Value column (G):** Constant shows its value (with the test's
  formatting if set); Multiple Choice its choices; Wraparound "low to high"
  (no trailing ".0"); Composite, String Composite and Upload the first line
  of the calculation in monospace, cut at 60 characters with the full text
  as a tooltip. Upload's auto-filled `<slug> = None` placeholder counts as
  no calculation. Long choice lists are cut the same way. Other types show
  "None".

- **Outline in the builder and preview (D):** an outlined sublist card gets a
  2px `#424f57` border. The preview copies the Perform QC page, which draws a
  3px grey rule above and below the sublist with its name in italics (not a
  full box), and shows the sublist description under the name.

- **Add buttons (C):** order in the Tests & Sublists header is Expand All,
  Add Sublist, Add Test. The drag caption went with the bottom bar; the drag
  handles keep their "Drag to reorder" tooltip.

- **Test counts (A):** the Tests & Sublists badge and the page header both
  show the total number of tests, including tests inside sublists; the
  header reads "N tests · N sublists" (it said "sections").
- **Description and Duplicate dialogs (A):** kept saving straight away, and
  said so in each dialog, rather than deferring to the test list's Save.
- **Parent Memberships card (A):** now directly below Tests & Sublists, above
  Attachments.
- **List page Search button (E):** styled as a secondary button, so "New
  Test List" stays the page's one primary action.
- **List page on narrow screens (E):** at 1024px wide and below, the filter
  card moves above the results, full width, with its groups side by side.
  Each filter group is capped at 180px tall there and scrolls past that.
  Results get a minimum height of about one screen (CSS, not JS).
- **Filter group caret (E):** Font Awesome caret instead of the browser's
  marker, to match the card's funnel icon.
- **Page titles (B):** "Test Lists | QATrack+ Admin Site", "Add Test List |
  …", and "<name> | Edit Test List | …", replacing Django's "Select test
  list to change" / "Change test list".
- **Breadcrumb changelist link (B):** doesn't carry the list page's filters,
  same as Django 4.2's default.

## New issues found

- Perform QC (existing): Yes/No references show as "1"/"0" in the
  Reference column (same root as the Unit Test Info admin issue above). (L)
- `PerformQA.set_unit_test_infos` passes an already-formatted "Do not
  treat…" string to `_()`, so it can't be translated. (L)
- New translatable strings (including one in `qa.js`, djangojs domain) need
  `makemessages`/`compilemessages` before release. (L)

- The Assign success note makes the Editing bar wrap at 1440px until it
  fades, pushing Editor/Preview to a second line. (K)
- A generic click handler hides any clicked `.tl-modal-backdrop` directly,
  bypassing each dialog's own close logic. Harmless today. (K)

- Save As in browsers without `requestSubmit` falls back to `form.submit()`,
  which skips the submit event, so the browser's leave prompt would show.
  Old browsers only. (I)
- "Assign to machine…" on the add page is disabled with an inline style and
  `href="#"`; the assign dialog task (K) replaces it. (I)

- Dark admin theme: the "Edit Test List" title (`.tl-header-title`, `#333`)
  is nearly invisible. Existed before; for the design pass. (H)
- Below 1024px wide, admin pages in general scroll sideways. Not builder
  specific. (H)
- `/admin/password_change/` logs 404s and RequireJS errors for
  `zxcvbn`/`password_strength`. Unrelated. (H)
- Test List list page: the filter card (~860px) is taller than a 900px
  window, so the page scrolls a little and the top of the results card goes
  under the pinned header. Shortening or internally scrolling the filter card
  would fix it. (H)

- `RemovedInDjango50Warning` (filtering by an unsaved instance) still comes
  from `TestForm.clean` (`qa/admin.py` ~1894) and `qa/signals.py:177`
  (`on_test_save`), plus test helpers. Not builder code. (P)
- The "duplicated macro names" error lists slugs after " :: " with bare
  commas; terse for clinical staff. (P)
- A user without delete permission on the inlines can mark a row removed in
  the builder; validation now ignores that row but the formset won't delete
  it. Edge case, not handled. (P)

- **Builder validation bugs (fixed in task P):**
  - `TestListAdminForm.clean` counts every posted test and sublist,
    including rows marked for removal, so removing a duplicate test in the
    builder and saving still fails with "duplicated macro names". (F)
  - After a validation error, an existing row that was removed in the
    builder comes back as not removed, because the DELETE checkbox always
    renders unchecked. (F)
  - Fixed in task F: unsaved rows used to disappear when the page came back
    after a validation error. (F)
- `TestListMembershipInlineFormSet.__init__` filters by an unsaved TestList
  on the add page, raising Django's `RemovedInDjango50Warning`. (F)

- Possible follow-up: edit references and tolerances inline in machine
  mode, instead of through the Unit Test Info page. (J)
- `UnitTestInfoForm.save` (`qa/admin.py` ~line 212) stores Yes/No references
  with the default numerical type, so the Unit Test Info admin list shows
  "1"/"0" instead of Yes/No. Existed before this work. (J)
- The tolerance format ("Percent(-3.00%, …)", "M.C.(OK=a:b, …)") reads like
  code; clinical staff may want plainer wording. (J)
- Narrow screens: at 800px the builder table scrolls sideways inside its
  card, so Type Value / Reference / Tolerance are off-screen until scrolled.
  (J)
- The builder lets you add a sublist containing a test that's already a
  direct test (or in another sublist). Saving then fails with "test macro
  names are duplicated". Better to warn when adding. (J, found via seed data)
- `makemigrations --dry-run` lists pending migrations for faults, parts,
  units, attachments, qa, reports and service_log at the commit this work
  started from. Unrelated to the builder; worth checking on `develop`.

- Live preview (`renderLivePreview`): its other column headers, "Untitled
  Test List", "Value..." and "JavaScript logic active on perform page" are
  hard-coded and untranslated, some with inline styles, and it inserts the
  description as raw HTML. The preview is due to be rebuilt (task L). (G)

- "Change" on an existing sublist swaps in a card built as if the sublist
  were new: empty `children-N-id` and an unchecked outline box. The existing
  sublist's outline setting, and its pairing with the saved row, are lost on
  swap. Existed before this work. (D)

- `qatrack/admin_media/js/m2m_drag_admin_testlist.js` (changed heavily on this
  branch) isn't loaded by any template; the builder JS is inlined in
  `testlist_assets.html`. It still refers to the removed bottom bar buttons.
  Looks like a stale copy to delete. (C)
- `.tl-header-add-btn` keeps a leftover `margin-left: auto`; `.tl-header-text-btn`
  ("Expand all") uses 11.5px and sentence case. Covered by the design pass and
  wording tasks. (C)

- `testlist_duplicate_test` didn't set `created_by`/`modified_by`, so every
  Duplicate failed with an IntegrityError. Fixed in task A (outside its plan,
  needed for the feature to work at all). (A)
- `testlist_test_desc_modal` saves with `update_fields=["description"]`, so the
  Test's `modified`/`modified_by` aren't updated after a description edit. (A)
- `testlist_duplicate_test` copies the source test's references and
  tolerances on every unit with no `change_unittestinfo` permission check, and
  the copies share the same Reference objects instead of new ones. (A)
- The Duplicate click handler puts whatever the server returns into the
  dialog without checking `res.ok`, so a 403/500 page would show as raw text.
  Harmless while the button is hidden without permission. (A)
- The description dialog's label has no label styling, unlike the new
  Duplicate dialog fields. (A)
- `qatrack/templates/admin/change_list.html`: the project's changelist
  override never renders Django 4.2's "Clear all filters" link, on any admin
  list page. (E)
- `qatrack/templates/admin/change_form.html:42`: the site-wide breadcrumbs
  show the changelist link only with `has_change_permission`; Django 4.2
  uses `has_view_permission`, so view-only users lose the link on other
  admin pages. (B)
- Test List list page, narrow screens: the results table keeps fixed column
  widths, so names wrap a lot and the edit pencil column scrolls sideways
  inside the results box at about 800px. No page-level overflow. (E)
- `initResultsScroll` only recalculates on window resize, not when a filter
  group opens or closes. Minor now that CSS sets a minimum height. (E)
