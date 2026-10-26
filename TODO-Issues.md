# Test List Builder: issues for review

Temporary. Issues found while working through `TODO-test-builder.md`, plus
any task that didn't succeed within three attempts. For the maintainer to
review; remove before merging.

## Tasks that need review

_None yet._

## Decisions made during implementation

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
