# QC admin pages: design update to do

Working list for restyling the rest of the **QC** section of the Django admin
to match the Test and Test List pages built on `feat/test-builder`, and adding
features to them. This branch starts from `feat/test-builder` so it can reuse
that work's shared partials in `qatrack/qa/templates/admin/qa/shared/`.

Remove this file before the branch is merged.

## Decisions

- **Design source: `docs/developer/design_system.ai.md`** on branch
  `feature/design-system` (read it with
  `git show origin/feature/design-system:docs/developer/design_system.ai.md`).
  Where it lists an A11Y fix for a colour, new text uses the passing shade, as
  the Test List page already does (e.g. link `#317399`/`#357da7`, meta
  `#6e7785`, faint `#6d7787`, danger text `#c0392b`). Status colours always come
  with their word.
- **Restyle and add features.** Each page below lists its features.
- **Scope is the `qa` app** (the "QC" heading on the admin index).
- **Built in parallel:** step 1 is done here first; each step 2–4 group is then
  built on its own branch from step 1 and merged back.

## Ground rules (learned on `feat/test-builder`)

- **No new static files and no new `Media` JS.** The deployment runs
  `DEBUG = False`, so uncollected static files 404, and hx-boost doesn't re-run
  scripts in `<head>`. CSS and glue JS go in templates `{% include %}`d in the
  page body. Existing `Media` JS and already-collected static files (colour
  picker, ace, cal-heatmap, `tolerance_admin.js`, htmx, Font Awesome) may stay.
- **Override location:** templates go in `qatrack/templates/admin/qa/…`
  (project `TEMPLATES.DIRS`, searched before the app folders, so an app-level
  copy of the same name is silently ignored). Partials included by name can
  live in `qatrack/qa/templates/admin/qa/…` as the shared ones do.
- **Render fields on the server**, never by moving the DOM with JS.
- **Scope CSS to `#content-main`**; no bare element selectors; check light and
  dark admin themes (pin colours on white cards).
- **New endpoints** are admin views (`admin_site.admin_view`, permission
  checked), added in the page's ModelAdmin `get_urls()`; htmx partials return
  422 with the form on validation errors.
- Watch for editor format-on-save mangling `{% static %}`/`{% trans %}` tags.
- All strings `{% trans %}` / `_()`; Title Case titles and buttons, sentence
  case help; Canadian spelling in new text. Don't run `makemessages` on a
  parallel branch (it's done once after merging).

## Step 1: Shared QC admin template ✅

- [x] Generic list styles moved out of `testlist_assets.html` into
      `admin/qa/shared/_changelist_css.html`; filter collapsing and results
      scrolling into `admin/qa/shared/_changelist_js.html`
      (`window.qaChangelist`). The Test List page includes both.
- [x] Collapsed filter template moved to `admin/qa/shared/filter.html`.
- [x] `qatrack/templates/admin/qa/change_form.html`: pinned title row with the
      one save button group; each fieldset a card
      (`admin/qa/includes/qc_fieldset_card.html`); each inline a card; the
      attachments inline as the shared attachments card. Blocks for per-model
      templates: `qc_title`, `qc_header_meta`, `qc_header_actions_extra`.
- [x] `qatrack/templates/admin/qa/change_list.html`: title + count, object
      tools as buttons, results card with search, filter card. Blocks:
      `qc_list_title`, `qc_results_title`, `qc_results_icon`.
- [x] `admin/qa/shared/_qc_assets.html`: the CSS + JS both templates include.
- [x] `QCAdminDesignMixin` (qa/admin.py) on every QC admin: collapsed filters,
      and the optional `qc_fieldset_icons` / `qc_wide_fields` /
      `qc_inline_icons` card settings (`qatrack/qa/templatetags/qc_admin.py`).
- [x] Tests: `qatrack/qa/tests/test_qc_admin_design.py` (cards, buttons, saves,
      errors, view-only, every QC list/add/change page renders).

## Step 2A: Statuses, Tolerances, Auto Review ✅

- [x] **Test Instance Statuses:** fieldsets (Details; Behaviour: default,
      requires review, valid, export; Colour). Colour picker still works.
      List: the colour column becomes the design spec's status label (coloured
      border, black text, the status name). Feature: **live label preview**
      beside the colour field, updating as the name or colour changes.
- [x] **Tolerances:** fieldsets by type ("Type", "Limits"), `tolerance_admin.js`
      still shows/hides the right fields. Feature: **limits preview**: a strip
      showing Act low / Tol low / Tol high / Act high (or the multiple-choice
      OK / Tolerance lists) as they're typed, with an inline warning when the
      limits are out of order (the server check stays). Feature: **Used In**
      card on the change page: how many Unit Test Infos use this tolerance,
      linking to the Unit Test Info list filtered to them. (The old script
      hid fields by `.form-row`, which the cards don't have, so
      `tolerance_assets.html` does it now and the script isn't loaded.)
- [x] **Auto Review Rules:** list_editable pass/fail and status work in the
      restyled list; status shown as a label.
- [x] **Auto Review Rule Sets:** Feature: the `filter_horizontal` rules picker
      becomes a **checkbox list of rules** grouped by pass/fail, each with its
      status label. The "must be one default" error still renders. Used In
      card: tests using this rule set.

## Step 2B: Frequencies, Categories, Autosaves ✅

- [x] **Frequencies:** `admin/qa/frequency/change_form.html` extends
      `admin/qa/change_form.html`. Cards: Details (name, slug), Due Window
      (window start/end), Schedule (recurrence widget, full width), Preview
      (cal-heatmap). Feature: **"Next due dates" list** (next 8 occurrences)
      under the preview, updated over htmx as the schedule changes. Feature:
      **Used In** card: assignments using this frequency.
- [x] **Categories:** change form via the shared template (parent, name,
      slug, description). Tree changelist (django-mptt-admin) keeps its tree;
      add the title row above it if its template allows. Feature: **Used In**
      card: tests in this category, linking to the filtered Test list.
- [x] **Autosaves:** list restyled; "Recover" reads as a button-like link;
      Feature: change page shows a read-only summary card (unit, test list,
      who/when, number of values saved) with a Recover button.

## Step 3A: Test List Cycles

- [ ] Details card (name, slug, description, drop-down label, day option
      text) — description and JavaScript stay ace editors but span the card.
- [ ] Feature: **builder-style "Test Lists in This Cycle" card** replacing the
      tabular inline: numbered day rows, drag-and-drop reorder, remove, and an
      htmx **search picker** to add test lists (same look as the Test List
      builder's add-from-search). Order still saved through the inline formset.
- [ ] Attachments card. Feature: **Used In** card: assignments of this cycle.
- [ ] List: name, number of days, test lists summary, assignments count.

## Step 3B: Assign Test Lists to Units (Unit Test Collections)

- [ ] Own `admin/qa/unittestcollection/change_form.html` extending the shared
      one, replacing `admin/treenav/menuitem/change_form.html`. Cards: What
      (content type + object), Where & When (unit, frequency, active), Who
      (assigned to, visible to).
- [ ] Feature: **htmx object picker**: choosing Test List or Test List Cycle
      then searching for it, replacing the `updatecombo` select reload.
- [ ] Feature: **contents preview** card: the chosen test list's tests (or the
      cycle's days) read-only, and a link to its builder.
- [ ] List: `list_editable` active and `save_as` keep working; frequency and
      assigned-to shown as tags.

## Step 3C: Set References & Tolerances (Unit Test Infos)

- [ ] List: custom `admin/qa/unittestinfo/change_list.html` extends the shared
      list ("Copy References & Tolerances" button). Reference and tolerance
      columns show "Not set" highlighted where it causes "No Tol Set".
- [ ] Feature: **set reference & tolerance from the list**: a pencil on each
      row opens the Test List builder's machine dialog
      (`_machine_ref_tol_modal.html` + its endpoints / shared save helper) and
      updates the row in place.
- [ ] Change form: Details card as a description list (unit, test, current
      reference and tolerance), Reference Value card, History card using the
      history table (Before → After, newest first).
- [ ] `history.html`, `set_multiple_refs_and_tols.html`,
      `copy_refs_and_tols.html` / `_preview.html`: title row + cards.

## Step 4: Test List Instances, Test Instances, test packs

- [ ] TLI / TI change pages through the shared template, with sensible
      fieldsets; TLI `delete_confirmation.html` restyled (cards listing the
      linked service events). Feature: a "View on site" button to the TLI's
      review page.
- [ ] Test pack import/export pages: title row + cards.

## Checks for every step

- `uv run pytest -m "not selenium"`; `uv run ruff check .`; `ruff format` only
  on changed Python files.
- Look at each page in a running admin, light **and** dark theme, at desktop
  and ~768px.
- Save, Save and Continue, Save as New, Delete, validation errors and view-only
  users all still behave.
- Docs to check (per `AGENTS.md`): `docs/admin/qa/` (screenshots and field
  descriptions for these pages).
