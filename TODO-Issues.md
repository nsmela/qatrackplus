# Test List Builder: issues for review

Temporary. Written while working through `TODO-test-builder.md`, for the
maintainer to review. Remove before merging.

Every item in `TODO-test-builder.md` is done. No task needed more than three
attempts, so nothing was skipped. Each task was done by an agent with a
written plan, then checked (tests, lint, screenshots) and committed on
`feat/test-builder`. The whole project test suite passes (1652 tests).

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
  duplicate check, which now includes the limit-order check. A duplicate
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

## Issue round: what each fix did

Every open item from the previous version of this file was given to its own
agent. Commits: `211c7e1`, `9f9a7ec`, `aded961`, `00feb64`, `e931c05`,
`f2cc15f`.

### Builder items (all fixed)
- **Change on a sublist** keeps its saved row (same id, order and outline)
  instead of nesting a new row; focus returns to Change. Typing in the
  search box now filters (the input had no `name`).
- **Repeated tests** are blocked in the Add Test / Add Sublist / Change
  dialogs (warning and disabled button, re-checked at click time).
- **Duplicate Test** copies references only with `change_unittestinfo`,
  makes new Reference rows (tolerances stay shared) and records history.
  Without the permission the copy starts with no unit settings.
- **Description edits** update `modified`/`modified_by` and add a History
  entry; unchanged saves do nothing.
- **Duplicate errors** (403/500/network/expired session) show a short
  message, never raw HTML.
- **Dialog backdrops** close through each dialog's own close function;
  dragging a text selection out of a dialog no longer closes it.
- **Delete permission**: saved rows show a locked remove button with a
  tooltip; validation only skips rows that will really be removed. Also
  fixed: a row added then removed was saved anyway without the permission.
- **Save As** in old browsers no longer triggers the leave prompt.
- **Contrast**: on the Test List pages links are `#357da7` (white only) or
  `#317399` (anywhere the background changes) and grey text `#6b6b6b`.
- **Narrow screens**: the builder table and list results fit down to 800px
  (sidebar collapsed) / 1024px (open) using container queries.
- **List filter card** scrolls inside itself; the page no longer scrolls at
  1440×900; results resize with the pinned header and filter toggles.
- **Stale JS**: `m2m_drag_admin_testlist.js` deleted, with a guard test.
- **Tolerance wording** in the builder is plain ("Tolerance −1 to 1 ·
  Action −2 to 2", "OK: a, b · Tolerance: c", "Action if wrong"); the
  stored name stays as a tooltip. `Tolerance.__str__`/`name` unchanged.

### Elsewhere in QATrack+ (fixed)
- **Percent tolerance with a changed reference** (bug confirmed): the form
  now validates against the new reference.
- **Unit Test Info history** reads Before → After, newest first, with
  "Not set" and "(No change)".
- **Yes/No references** are saved with the boolean type; older 1/0 ones read
  Yes/No everywhere a test is known (admin, Perform QC, reports, history).
  Display fix only, no data migration.
- **Perform QC repeated tests** (real bug): a test both direct and in a
  sublist made two rows and saved two conflicting values; composites used
  the last. `TestList.ordered_tests()` now lists each test once (first
  position), which also affects the API, history, charts and reports for
  such lists only.
- **"Do not treat…"** is one translatable string with a placeholder.
- **Deprecation warnings** (filtering by unsaved instances) are gone from
  the whole suite. Found on the way: `on_test_save` compared the test type
  with `is not`, so its Boolean-reference check rarely ran. It now runs (see
  Decisions) and the admin form reports it instead of a 500.
- **Dead `export_test_lists` action** removed.
- **Admin change forms** get `id="<model>_form"`; breadcrumbs follow view
  permission.
- **Admin list pages** show "Clear all filters", and results fill their
  column (Django 4's `changelist-form-container`).
- **"Submitting…"**, the home tooltip and calendar month names are
  translatable.
- **Admin pages on narrow windows** no longer scroll sideways (index layout,
  filter-horizontal selectors, long names, paginator, wide inlines).
- **Password pages** no longer request the removed zxcvbn library (404s and
  RequireJS errors; their focus code works again).

### Decisions from this round to review
- **Boolean reference check now enforced:** with `is not` fixed, a full save
  of a Boolean test is refused while any unit has a reference other than
  0/1. Old data in that state now blocks full saves of those tests until the
  references are fixed (description-only saves still work).
- **Repeated tests**, first occurrence wins. Sessions saved before the fix
  can still hold two TestInstances for one test; their review/edit pages
  will show duplicate rows. No data repair was done.
- **Duplicate Test without `change_unittestinfo`** creates no unit settings
  at all; the usual signals create empty ones when the list is saved.
- **Locked remove buttons** rather than hidden ones, so users see why.
- **Two link blues** on the Test List pages (could be unified on
  `#317399`).
- **Backdrop clicks** still close dialogs with typed input, as Cancel does.
- **Tolerance wording** uses the site's status names (not "Tol"/"Act") and
  shows limits as differences from the reference; numbers aren't
  locale-formatted.
- **Filter-horizontal selectors** keep their 980px desktop width.
- **No password strength meter**: zxcvbn wasn't vendored back.

## Left out on purpose

- **Pending migrations** (you chose to leave them out of this branch).
  `makemigrations --check` fails at the starting commit for attachments,
  faults, parts, qa, reports, service_log and units: about 200 `AlterField`
  operations syncing field options (verbose names, help text, related names,
  Python defaults). They produce no SQL on SQLite (not checked on
  PostgreSQL/SQL Server). They belong on `develop`.
- **"seperated" typo**: fixed (Tolerance multiple-choice help text and
  `Test.choices`), without a migration. The help-text change just joins the
  pending metadata migrations above. The fr, fr_CA and es `.po` files hold
  the old msgids; carry the French translations over when running
  `makemessages`. The Spanish one for `Test.choices` is a different
  sentence ("Debe dar al menos 1 opción…") and needs retranslating.
  The docs typo is fixed too. `Test.choices` has `verbose_name="Description"`;
  the Test admin form now labels it "Choices", but the model's
  `verbose_name` should be fixed with the pending migrations, after which
  the label overrides listed under N30 can go.

## Round 2: what each fix did

Every item that was under "Open issues found in this round" had its own
agent. Test files are `test_round2_<id>.py` next to each app's tests.

Builder:
- **N1** List page buttons wrap on narrow windows (no sideways scroll at
  400–800px; 1440px unchanged).
- **N2** Builder dialogs keep light inputs in the admin dark theme (a
  separate light-variable rule on `.tl-modal-dialog` and its containers).
- **N3** "Not used"/"Save the test list first" text in machine mode, and the
  empty-sublist message, use `#5f6773` (5.3:1 on hovered rows). Icons in the
  old grey pass 3:1 and stay.
- **N4** The same test added twice directly now gets the builder's own
  message naming it; Django's generic duplicate message is turned off for
  the builder's membership formset (the form check covers it).
- **N5** The Remove button and DELETE box on saved attachments only show
  with delete permission. The server already ignored the DELETE; the
  attachment just came back after saving.
- **N6** Saved sublist cards render their `-id` input once.
- **N7** Sublist row colspans match the visible columns in base and machine
  mode (updated in JS on mode switch).
- **N8** On windows ≤1024px the list page's filter groups start collapsed,
  except ones with an active filter or ones the user opened.
- **N9** The list's header padding now applies (on Django's inner
  `.text > a/span`); headers are 2px shorter, columns unchanged.
- **N10** "and N more" uses a real plural form.
- **N11** The description and Save As submits have their own classes (the
  clash was latent; nothing misbehaved).

Elsewhere:
- **N12** Assignments list no longer 500s when an assignment's group was
  deleted; it shows "Not assigned".
- **N13** Room add page no longer 500s (Storage inline's unsaved rows).
- **N14** Admin app list is back where the nav sidebar can't show it (narrow
  windows, collapsed sidebar, `/admin/<app>/` pages, staff with no
  permissions). Upstream removed it on purpose (26580c2a); beside an open
  sidebar on desktop it stays hidden.
- **N15** Perform QC has no repeated ids; upload tests render their hidden
  inputs once.
- **N16** Perform QC's reference/tolerance text is translatable, escaped, and
  uses `<br>`; limits come from the tolerance type, not its stored name.
- **N17** `base.js` "Submitting…" is translated with a working `disabled`
  class; the admin guard no longer blocks a resubmit after a cancelled one.
- **N18** `reference_changed` is only recorded when the value really changes.
  The history display's workaround stays for older rows.
- **N19** Test page shows "Not set" instead of None for unit refs/tols.
- **N20** API adds a read-only `reference_display` (unit test infos and the
  submitted test list response); `type`/`value` unchanged.
- **N21** Global admin change form matches Django 4.2 (body classes, object
  tools tag, `to_field`, "Add …" breadcrumb).
- **N22** Global admin change list loads `filters.js` and pluralises the
  error note.
- **N23** Test pack export/import JS strings are translatable; "…" in the
  templates. The second copy is just collectstatic output.
- **N24** `drag_admin.js` and `jquery-1.7.1.min.js` deleted.
- **N25** "Succesfully"/"Successfuly" typos fixed; `.po` msgids corrected and
  `.mo` rebuilt.
- **N26** The zero-reference log message is logged in English.
- **N27** The last `default.html` deprecation warning (review page's bare
  `{{ form }}`) is gone; markup unchanged.
- **N28** Duplicate Test goes through the Test admin's own permission and
  queryset checks; 404 for a bad id. No data was exposed beyond what the Test
  admin already shows.
- **N29** Developer guide typos fixed.
- **N30** `choices` is labelled "Choices" in the Test admin form, the API
  filter form and the API serializer. The model fix is pending (above);
  after it, remove `TestForm.Meta.labels`, `TestFilter.filter_for_field` and
  `TestSerializer.Meta.extra_kwargs`.
- **N31** (found by N5) Saving a test list no longer wipes the comments on
  its saved attachments (the cards now post them back as hidden inputs).
  Browse… only shows with add_attachment.
- **N32** (found by N6) Saved test rows render their `-id` input once (they
  printed it twice, like the sublist cards).

### Decisions from round 2 to review
- **Data loss on the Unit Test Info admin page (already on `develop`):**
  leaving "New reference value" blank while changing only the tolerance
  clears the unit's reference. `UnitTestInfoForm.save()` does this on
  purpose (`elif 'reference_value' in self.cleaned_data: … = None`). The
  builder's Reference and Tolerance dialog keeps the reference instead.
  Decided: blank keeps the current reference (to do in
  `TODO-test-builder.md`, Round 3).
- **Duplicate Test** now needs add_test plus view_test or change_test; users
  with only add_test lose the button. GET still renders the dialog (only POST
  creates).
- **Filter state:** the list page stops Chrome's automatic `toggle` events
  reaching Django's `filters.js`, so it only remembers real clicks.
- **Admin index:** upstream's "no duplicate app list beside the sidebar"
  kept. Stock Django's layout is a two-line change if preferred.
- **API:** `reference_display` isn't on `/api/qa/references/` (a reference
  isn't tied to one test) or on nested test instances (query cost).
- **Spanish:** the password page heading now uses the title's translation
  ("Contraseña cambiada con éxito").
- **`.mo` files** were rebuilt with GNU msgfmt (installed in this container),
  so they're larger than Babel's (hash table); contents match.
- **Reference type on Boolean tests** is ignored when deciding whether the
  reference changed.

### Open issues found in round 2
Builder:
- `change_form.html` renders formset `non_form_errors` directly inside the
  tests `<tbody>` (invalid HTML; errors land oddly).
- `.tl-empty-sublist-msg` and `.tl-cell-lock` lose their colour/padding to
  `.tlb-table tbody td` (specificity).
- `"%(count)s test(s)"`/`"sublist(s)"` in `TL_STRINGS` are two msgids, not a
  plural pair.
- At 400px the results table scrolls sideways inside its card.
- `testlist_test_desc_modal` and `testlist_add_test_row` use a raw
  `get_object_or_404(Test…)` (a non-numeric id may 500).
- No general hook when the builder's mode class changes (new code must call
  `syncColumnSpans()`).
- `.tl-modal-dialog` itself inherits the dark body colour in dark mode (all
  current text sets its own).

Elsewhere:
- Assignments: no "unassigned" filter option; `assigned_to` is `null=True`
  but not `blank=True`; `get_content_type` can raise on a stale content type.
- Parts: `ContactInline` has dead `_get_queryset`/`_formfield_for_foreignkey`;
  Room change page's "Loading..." text stays visible.
- `qa_tags`: a boolean tolerance on a non-Boolean test renders "None";
  `TEST_STATUS_DISPLAY` defaults aren't translatable.
- `base.js` `preventDoubleSubmit` still marks the form before later handlers
  run (not hit today).
- `service_event_update.html:57` "Submitting Service Log..." untranslated.
- `qavalue_form.html` puts hidden inputs directly inside `<tr>`.
- Review page form errors render `<tr>` inside a `<form>` with no table.
- Test pack pages: "Test Lists Cycles:" wording, raw HTML shown in export
  descriptions, inline styles, dead `coltype flex`, unused vars in
  `testpack-import.js`.
- `copy_refs_and_tols.html` uses the old body class.
- `app_index.html` hard-codes untranslated "Websites"; the nav sidebar
  doesn't highlight the current app.
- Password reset complete page uses a bare `<h1>`; es `.po` has a fuzzy
  "You may change it again…" entry.
- `set_multiple_references_and_tolerances` records no history.
- Same-value reference saves still create new Reference rows.
- The local dev database's "Daily Linac QC" has t3 both directly and in its
  "Imaging Checks" sublist, so it can't be saved unchanged (check whether
  that came from seed data or an agent's setup).
- `qa_utils.create_test_list` makes slugs the change form rejects.
- `SaveInlineAttachmentUserMixin.save_formset` sets `created_by` on every
  changed attachment, not just new ones.
- API filter forms show duplicate labels where a field has both `contains`
  and `icontains` ("Name contains" twice).
- `initAttachmentsSection` re-binds its document-level Remove listeners each
  time it runs.

## Round 3: decisions and open issues

All eight Round 3 items in `TODO-test-builder.md` are built (one agent each).

### Decisions to review
- **Blank reference keeps it (R1):** the Unit Test Info admin page has no way
  to clear a reference on purpose (the builder dialog still can, by emptying
  its filled-in field). A "Clear reference" checkbox would be the follow-up
  if needed. String-type tests no longer drop a stale reference on save
  (they never read it).
- **Type chip (R2)** uses the Category pill's neutral look; no colour per
  type (colour means QC status). The old short-badge translations go
  obsolete at `makemessages`.
- **Reference & Tolerance column (R3):** String and String Composite show
  their tolerance only (they pass/fail by choices, like Multiple Choice);
  Boolean shows "Expected Yes/No", plus a tolerance line when one is set;
  Upload/Date types show "No limits needed".
- **Machine-mode pencil** (R5, then R11) sits at the start of the Reference &
  Tolerance cell in a fixed 24px slot (empty when there's no pencil, so
  values line up), in its blue machine style. Machine mode has no actions
  column.
- **Sublist headers top-align (R4)** like test rows, so the drag handle stays
  by the first line when a long name wraps.
- **Heading (R6)** reads "Edit Test List · ID 123"; the browser tab title is
  unchanged (it already leads with the name).
- **Description links (R7):** "Add Description" stays as a link to the Test
  page (hidden in machine mode); an existing description stays clickable in
  machine mode since it only opens another page.

### Open issues found in round 3
- Fixed since: the tests table now fits its card down to a ~370px card
  (cells compact and wrap; nothing hidden). Below that (360px phones) it
  still scrolls inside the card; a card-style row layout would fix it.
- Base-list action icons and the machine pencil are under 24px at wide
  widths (only the narrow steps enforce 24px tap targets).
- `UnitTestInfoForm`'s class-level labels ("New reference value", "Set by",
  …) use eager `gettext`, so they don't follow the request language.
- `test_round2_N7.py`'s docstring and a comment near `test_admin.py:2096`
  still describe separate Reference / Tolerance columns.
- The dev database has throwaway objects from agents' browser checks (e.g.
  "R3 Demo List", "R5 Span Check", "R7 dup …", "N18 throwaway output").

## Before merging

- Run `makemessages -l fr -l fr_CA -l es` (django and djangojs domains) and
  `compilemessages`; there are many new and changed strings.
- Run `collectstatic` on deployment: the collected RequireJS config still
  lists the removed zxcvbn entries until then.
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
- Tolerances accepted limits out of order (e.g. Tolerance Low 2, Tolerance
  High 1). `Tolerance.clean_tols` now requires Action Low ≤ Tolerance Low ≤
  Tolerance High ≤ Action High (blank limits skipped), for the Tolerance
  admin and the builder alike. Existing tolerances out of order aren't
  changed, but can't be saved again until fixed.
