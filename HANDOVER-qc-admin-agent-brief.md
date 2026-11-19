# Brief shared by every QC admin page agent

You are one of several agents restyling QATrack+'s QC admin pages in parallel, each on
its own git worktree and branch. Read this whole file first, then your own task.

## The project

QATrack+ is a Django 4.2 app (Python 3.12, `uv`) for radiation-therapy clinics. Read
`AGENTS.md` at the repo root. Work only in your own worktree.

## Where things are

- Plan and per-page specs: `TODO-qc-admin-design.md` at the repo root. Your task names
  the section(s) you own. Tick off its checkboxes when you're done (edit only your own
  sections of that file).
- Design spec: `git show origin/feature/design-system:docs/developer/design_system.ai.md`.
  Use its values as literals. Where its A11Y section gives a passing shade, use that for
  new text (the Test List page does: link `#317399`/`#357da7`, meta `#6e7785`, faint
  `#6d7787`, danger text `#c0392b`). Status colours always come with their word.
- Step 1 (already committed, your base) gives every QC model a shared card layout:
  - `qatrack/templates/admin/qa/change_form.html`: title row + save buttons, fieldsets as
    cards (`qatrack/templates/admin/qa/includes/qc_fieldset_card.html`), inlines as cards,
    attachments inline as the shared attachments card. Blocks to override: `qc_title`,
    `qc_header_meta`, `qc_header_actions_extra`, and Django's `field_sets`,
    `after_field_sets`, `inline_field_sets`, `after_related_objects`.
  - `qatrack/templates/admin/qa/change_list.html`: blocks `qc_list_title`,
    `qc_results_title`, `qc_results_icon`, `object-tools-items` (`{{ block.super }}` keeps
    the Add button).
  - `qatrack/qa/templates/admin/qa/shared/_qc_assets.html`: the shared CSS/JS.
  - `QCAdminDesignMixin` in `qatrack/qa/admin.py` (already on every QC admin) and
    `qatrack/qa/templatetags/qc_admin.py`: optional `qc_fieldset_icons`,
    `qc_wide_fields`, `qc_inline_icons` ModelAdmin attributes.
  - Tests: `qatrack/qa/tests/test_qc_admin_design.py`.
- Finished examples of the same design with features: the Test page
  (`qatrack/templates/admin/qa/test/change_form.html`, `qatrack/qa/templates/admin/qa/test/test_assets.html`)
  and the Test List builder (`qatrack/templates/admin/qa/testlist/change_form.html`,
  `qatrack/qa/templates/admin/qa/testlist/testlist_assets.html` — 5000 lines, search it,
  don't read it all; `partials/` beside it). Reuse their class names and patterns
  (`.tl-details-card`, `.tl-card-header`, `.tlb-form`, `.tl-count-badge`, `.tl-btn`, the
  builder's htmx search picker and sortable rows, its modal dialogs).

## Hard rules (each was learned the hard way)

1. **No new static files and no new `Media` JS/CSS.** Production runs `DEBUG = False`
   without collecting new static, and hx-boost doesn't re-run `<head>` scripts. Put your
   page's CSS and JS in a template partial you `{% include %}` in the page body (e.g.
   `qatrack/qa/templates/admin/qa/<model>/<model>_assets.html`). Existing `Media` entries
   and already-collected files (htmx `htmx/js/htmx.min.js`, jQuery, colour picker, ace,
   cal-heatmap, Font Awesome) may be used.
2. **Template location:** page templates go in `qatrack/templates/admin/qa/<model>/…`
   (searched before app folders; an app-level copy with the same name is silently
   ignored). Partials/assets may live in `qatrack/qa/templates/admin/qa/<model>/…`.
3. **Render fields on the server.** Never build the form by moving DOM nodes with JS.
4. **CSS scoped to `#content-main`** (or your page's own ids/classes), no bare element
   selectors, prefix new classes for your page (e.g. `qcs-` statuses, `qct-` tolerances).
   Cards are always white: pin text/background colours so Django's dark admin theme
   (which sets `--body-fg` light) doesn't make text invisible.
5. **Don't edit shared files**: `_qc_assets.html`, `_changelist_css.html`,
   `_changelist_js.html`, `_header_css.html`, `_card_form_css.html`, `_attachments_*`,
   `qatrack/templates/admin/qa/change_form.html`, `change_list.html`,
   `includes/qc_fieldset_card.html`, `qc_admin.py`, `QCAdminDesignMixin`, and the Test /
   Test List pages. Other agents depend on them. If you need a change there, work around
   it in your own partial and say exactly what you'd change in your final report.
6. **`qatrack/qa/admin.py` is shared by every agent**: only change your own ModelAdmin
   classes/forms/views; put new module-level helpers next to your ModelAdmin; don't
   reorder, reformat or move anything else (keeps the merge clean). Don't run
   `ruff format` on admin.py.
7. **Tests go in a new file of your own**, `qatrack/qa/tests/test_qc_admin_<group>.py`.
   Don't edit `test_admin.py` or other existing tests unless your change genuinely
   alters what they check (then say so in your report).
8. **New endpoints** are admin views in your ModelAdmin's `get_urls()`, wrapped in
   `self.admin_site.admin_view`, checking the right model permission; htmx partials return
   422 with the form when invalid. CSRF for htmx: `hx-headers='{"X-CSRFToken": "{{ csrf_token }}"}'`
   as the Test page does. Load htmx via the ModelAdmin's `Media` (`"htmx/js/htmx.min.js"`,
   already collected) as TestAdmin does.
9. **Strings:** `{% trans %}` / `_()` everywhere; Title Case titles and buttons, sentence
   case help and messages; plain, friendly language for clinical staff; Canadian spelling
   in new text. Do NOT run `makemessages`/`compilemessages` (done once after merging).
10. **Don't touch data behaviour you weren't asked to change.** Same fields, same
   validation, same permissions, same saved values. Features listed for your pages are
   additions.
11. Watch your editor/formatter: never reformat Django template tags.

## Setting up your worktree

- `qatrack/local_settings.py` and `qatrack/local_test_settings.py` are gitignored: copy
  both from `C:\Users\nsmel\source\repos\qatrackplus\.claude\worktrees\qc-view-design-updates-14aeb6\qatrack\`.
- `uv sync --dev` (first run takes a minute or two).
- Run tests with `uv run pytest -m "not selenium" <paths> -q -p no:cacheprovider -o addopts=""`.
  Your own test file plus `qatrack/qa/tests/test_qc_admin_design.py` and
  `qatrack/qa/tests/test_admin.py` must pass before you commit; run the whole
  `qatrack/qa` folder once at the end (it takes several minutes; run it in the
  background).
- `uv run ruff check <your changed .py files>`.
- **Don't use the browser pane** (other agents share it). Check your HTML through the test
  client and by reading the rendered output; the lead does the visual light/dark check
  after merging. Write tests that assert your markup renders (not just status 200), that
  saving still works, that validation errors render inside the cards, and that view-only
  users get a read-only page.

## Committing

- Check your base first: `git log -1 --format=%H` must be the step 1 commit given in your
  task. If it isn't, run `git reset --hard <that sha>` before changing anything (your
  fresh worktree has nothing to lose).
- Commit in small steps on your branch with clear imperative messages, each ending with
  a blank line and `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
  Never use `--no-verify`. If a pre-commit hook fails because of something outside your
  files, say so in your report. Don't push, don't open PRs, don't touch other branches.
  Don't use `git stash`.

## Your final report (keep it short)

- Branch name and the list of commit SHAs.
- What each page now looks like and what features you added (one line each).
- Anything you couldn't do, anything you'd change in a shared file (rule 5), any
  existing test you changed and why, and test results (counts).
