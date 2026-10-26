# Test List Builder: issues for review

Temporary. Issues found while working through `TODO-test-builder.md`, plus
any task that didn't succeed within three attempts. For the maintainer to
review; remove before merging.

## Tasks that need review

_None yet._

## Decisions made during implementation

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
