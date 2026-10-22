# QATrack+ design spec (agent-condensed; full: design_system.rst, data: design_system_tokens.json)
SRC nsmela/qatrackplus feature/htmx@ac800345. Describes code as-is; not a redesign.
LEGEND name=role label only; code has NO css vars → emit literal values. "a/b" = rule a, hover/active b. ⚠r = WCAG fail, r:1 on noted ground (AA text 4.5, ≥24px/bold19 3.0, UI marks 3.0). W=#fff. sfc=#fff. ONE theme (light). Keep failing values exact unless task is fixing them (§A11Y).

## STACK
AdminLTE 2.3.3 + Bootstrap 3.3.6 + FontAwesome 4.7 + htmx (deferred, site_base.html) + requirejs. Django templates, i18n en/fr/fr-ca/es.
CSS order (site_base.html): fontawsome/css/font-awesome.min.css, bootstrap/css/bootstrap.css, adminlte/css/admin-lte.css, adminlte/css/skins/skin-black-dark.css, qatrack_core/css/custom-adminlte.css, qatrack_core/css/custom-fontawesome.css, qatrack_core/css/base.css, qatrack_core/css/print.css, {%extra_css%} (fault details: service_log/css/sl.css via sl_base, datepicker, multiselect, daterangepicker, tables.css, custom-daterangepicker, faults/css/faults.css, +select2/custom-select2/flatpickr/flatpickr-custom if change_fault), qatrack_core/css/site.css.
Prefixes: tl-/tle- = shared in-place-edit blocks (base.css); fl- = fault details (faults/static/faults/css/faults.css).
<body class="skin-black-dark fixed layout-top-nav preload" hx-headers='{"X-CSRFToken":…}'> (body bg W; .wrapper chrome-bg; .fixed → header position fixed z1030, .content-wrapper pt50 min-h100% page-bg; .content pad 15).
htmx glue (site_base.html): beforeSwap 422→shouldSwap=true,isError=false (forms return 422+errors); responseError→alert 403 "You do not have permission to do that. Nothing was changed." else "Something went wrong on the server and your change was not saved. Please try again."; sendError→"The server could not be reached, so your change was not saved. Check your connection and try again."

## COLOUR name hex use
chrome-bg #222d32 header,sidebar,.bg-dark-gray; W on it 14.1
chrome-bg-deep #1e282c logo block, sidebar hover/active, sidebar-toggle hover
chrome-bg-header #1a2226 .sidebar-menu>li.header (fg #4b646f ⚠2.58)
chrome-bg-raised #323e46 control sidebar
chrome-text #fff nav links+logo; hovered/open nav item → #000 on W, side borders chrome-bg
chrome-text-muted #b8c7ce sidebar links 8.1
chrome-text-sub #8aa4af treeview links on #2c3b41 ⚠4.43
page-bg #ecf0f5 .content-wrapper
surface #fff boxes,dropdowns,inputs,picker results
surface-subtle #f4f4f4 .btn-default fill, input-group addon, .text-display; faint in-box divider (box-header.with-border, table row rule)
surface-foot #fbfcfd .tl-group-foot
surface-hover #f5f7fa hovered .tl-table row, .tl-pick-item
surface-chip #f6f7f9 .tle-attach-item
surface-code #f4f7f9 .fl-code-chip
surface-comment #f7f7f7 .box-comment (hover #f2f2f2)
surface-iconbtn-hover #eceff3 .tl-iconbtn:hover
surface-pending #eef6fb .fl-pending chip
border #d2d6de inputs, .box-default top, table th underline, label-default fill; 1.46 on W → never sole carrier of meaning
border-light #ddd .text-display, .drop-shadow, timeline icon, shadow colour (.dropdown-menu is #bbb)
border-chip #e2e6ee chip outline, .subheading-divider
border-code #dbe3e8 code chip outline
border-dashed #cbd1da .tle-attach-add
border-popover #b7bcc4 .fl-results
border-editing #cfe0ee edit-ring, pending chip outline
text #444 titles, .btn-default fg, label-default fg; 9.74 W, 8.51 page-bg
text-body #333 body (bootstrap), .fl-code; 12.63
text-label #555 field labels, dt, chip text; 7.46
text-desc #5a6472 .fl-desc; 6.00
text-muted #777 .text-muted, .popover ⚠4.48
text-meta #8a929e timestamps .fl-meta, .tl-table th, .tl-pick-sub, .fl-rec-label, .tle-attach-add ⚠3.14
text-faint #9aa2ae .tl-empty, .tl-pick-hint, .tl-field .help, .tle-attach-size, .fl-desc em, idle .tl-iconbtn, .fl-spin, .tl-search .fa ⚠2.58
text-crumb #97a0b3 .fl-breadcrumb ⚠2.30 on page-bg
text-code-chip #4a5763 on surface-code 6.89
primary #424f57 QAT+ override (not AdminLTE blue): .btn-primary, .box-primary/.nav-tabs-custom active top, nav-stacked active edge, alert/callout-primary; W on it 8.44
primary-hover #323e46 btn-primary hover/focus fill+border
primary-border-hover #212b33 btn-primary hover/focus border
info #627585 .btn-info, alert/callout-info (override); W 4.77
info-hover #4e6070 btn-info hover/focus
info-border #45454e btn-info/alert-info border
slate #748e9f .box-info top (default section box_class; Details overrides to box-primary), .box-solid.box-info header, chip file icon; 3.21 on surface-chip (icon/rule ok, not text)
link #3c8dbc a, btn/input focus border, .fl-editing-tag, .label-primary, .fa.primary ⚠3.67 W, 3.20 page-bg
link-hover #72afd2 .callout-custom a:hover
status-ok #00a65a QC OK .ok, success label/btn/callout, Reviewed .fl-rec-ok, .fl-saved, .fl-new bg, pick + icon; ⚠3.18 as text and W-on-it
status-ok-hover #008d4c btn-success hover/border
status-tolerance #f39c12 QC Tolerance .tolerance, warning label/btn, .fl-status-unrev border, DEFAULT_TEST_STATUS_COLOUR rgba(243,156,18,1); W on it ⚠2.19
status-tolerance-hover #e08e0b btn-warning hover/border
status-action #dd4b39 QC Action .action, danger label/btn/callout, required *, .errorlist, .fl-errors, .border-error outline, .red-bg; ⚠4.09 as text and W-on-it
status-action-hover #d73925 btn-danger hover/border
status-no-tol #00c0ef QC No Tol .no_tol, AdminLTE info label/callout; W on it ⚠2.15
status-not-done #b5bbc8 QC Not Done .not_done (bg only; .label W text ⚠1.93; #000 10.91 proposed)
unreviewed #b0761a .fl-unrev ⚠3.85
danger-deep #c0392b .btn-danger-ghost fg, .fl-missing fg/icon, .tle-attach-x:hover; 5.44 W, 4.64 on danger-ghost-bg
danger-ghost-bg #fbe9e7 .btn-danger-ghost hover, .tl-iconbtn.danger:hover
danger-ghost-border #e8c4be .btn-danger-ghost border (declared; hidden by .btn border transparent!important ⚠bug)
missing-bg #fdf6f5 .fl-missing; missing-border #edc9c3
comment-error #e76167 .err-comment (hover #d86268), W text ⚠3.33
chip-remove #b6bcc6 .tle-attach-x rest
Other literals in code: #999 nav-header fg & h1 small; #bbb dropdown border; #e7e7e7 sortable th hover; #e1e3e9 mobile dropdown hover; #0073b7 bg-blue; #001f3f navy; #39cccc teal; .bg-gray #d2d6de/#000; .bg-light-gray #eee.
DEFAULT_COLOURS (settings.py chart/status picks): rgba(60,141,188,1) rgba(0,192,239,1) rgba(0,166,90,1)×2 rgba(243,156,18,1) rgba(245,105,84,1) rgba(210,214,222,1) rgba(0,31,63,1) rgba(240,245,2,1) rgba(57,204,204,1) rgba(96,92,168,1) rgba(216,27,96,1) rgba(1,255,112,1) rgba(17,17,17,1). Model colour field validator: ^rgba(r,g,b,a)$.

## COLOUR RULES
Status colours = clinical meaning; never decorative; always with word (OK/TOL/ACT/NO TOL/Not Done; names configurable via TEST_STATUS_DISPLAY(_SHORT) — render configured name). DB/admin colours (service status, test status) → .service-event-status-label: transparent bg, 2px solid border = colour (inline style="border-color:{{colour}}" is the one allowed inline style), fg #000. Primary action = primary, not link blue; link never a button fill. Destructive in-section = .btn-danger-ghost; solid danger only on confirm pages. Box kind = 3px top border, not filled header.

## TYPE
Fonts (self-hosted woff2, NOT Google — clinics offline): qatrack_core/static/qatrack_core/fonts/Source-Sans-Pro-{300,300italic,regular,italic,600,600italic,700}/*.woff2 via qatrack_core/css/fonts.css; FontAwesome fontawsome/fonts/fontawesome-webfont.woff2 (sic "fontawsome").
families: sans "Source Sans Pro","Helvetica Neue",Helvetica,Arial,sans-serif | logo "Helvetica Neue",Helvetica,Arial,sans-serif | mono Menlo,Consolas,monospace | pre Menlo,Monaco,Consolas,"Courier New",monospace
style size/lh/weight[/ls] family: use
logo 20/50px/300 logo; <b>QAT</b>rack<b>+</b> (b=700), W on chrome-bg-deep; SITE_NAME replaces; collapsed "QAT+"
page-title 22/1.1/400 .fl-page-head h1, text
box-title 18/1/500 .box-title (h3: bootstrap 500, renders the 400 face), text (titles never bold)
subheading 15/1.42857/600 .subheading-divider, .box-small title
body 14/1.42857/400 default, text-body
body-strong 14/1.42857/600 label,.label,th,dt (QAT+ sets 600 not bold)
compact 13/1.42857(inherited)/400 htmx sections: descs, search inputs; field labels @600
small 12/1.42857(inherited)/400 meta, help(italic .help-block), breadcrumb, field errors, .tl-pick-sub; btn-sm 12/1.5
eyebrow 11/1.42857/700/.03em UPPER .tl-table th, .fl-rec-label, #box-others th; text-meta
tag 11/1.42857/700/.04em UPPER .fl-editing-tag; link
nav-header 11/18px/700 UPPER dropdown group captions; #999
badge 10/1.42857/700/.04em UPPER .fl-new W on status-ok
code 13/1.42857/700 mono .fl-code (.tl-mono: mono 13 only, weight from context); overflow-wrap:anywhere (wrap, never truncate)
code-chip 11/1.42857/700 mono .fl-code-chip
pre 12.025/18px/400 pre-family .pre, pre-wrap
Uppercase only eyebrow/tag/nav-header/badge.

## SPACE/RADIUS/SHADOW/SIZE
space 2 pick name↔sub | 4 result gap, chip gap, .box-small margin | 6 header tools gap, chips, desc actions | 8 foot btn gap, td v-pad, .fl-errors mb | 10 box header/body pad, td h-pad | 9/12 .tl-group-foot pad, .tl-form row gap | 15 page-head mb, gutter half | 16 .fl-layout gap, .tl-form col gap | 20 .box mb. No scale in code; these are used values.
radius 0 boxes(div.box override), alerts, .form-control, dropdowns, pagination, .btn-flat | 2px .label, .tl-search, .tl-desc-edit | 3px raised .btn, .tl-iconbtn, chips, .tl-pick-item, .fl-results. label-group ends .25em, badge-group .4em.
shadow box 0 1px 1px rgba(0,0,0,.1) | control 2px 2px 2px #ddd (!important on every .btn incl. .btn-flat, .btn-group, enabled input/select/textarea.form-control only; .btn-group .btn none) | inline-input 2px 2px 2px #eee (.tl-search,.tl-desc-edit) | dropdown 2px 6px 4px rgba(53,124,165,.25) (.dropdown-menu,.select2-dropdown,.popover,.drop-shadow) | header 2px 6px 4px rgba(50,62,70,.25) | sidebar 4px 6px 4px rgba(50,62,70,.35) | popover 0 8px 26px rgba(0,0,0,.18) (.fl-results) | editing 0 0 0 1px #cfe0ee,0 1px 1px rgba(0,0,0,.1)
size header-height 50 | sidebar-width 230 (logo; 186 sidebar-mini, 50 collapsed) | control-height 30 (.form-control; bootstrap 34) | iconbtn 24 | box-accent 3 | content-max-lg 1200 (.max-width-lg) | content-max-md 900 (.max-width-md; .fl-layout → 1 col ≤900px) | fault modal 800 | .tl-c-act 60 | .fl-se-id 70/.fl-se-status 110/.fl-se-date 100 | .fl-results max-h 300 | .fl-picker flex 1 1 120, min 120, max 420 | .tl-form cols minmax(220px,1fr) | .tl-desc-edit min-h 52 | dt 130/dd ml 146; .tight 96/108.

## VOICE
Audience clinical staff; plain, short, explain why ("When the fault happened, not when it was logged."). Title Case: page/box titles, nav, buttons ("Perform QC","Fault Types","Last Modified","Acknowledge This Fault"). Sentence case: help, empty states, messages ("No description available","New fault type, created when you save","No matches."). Buttons verb-first. Errors: what happened + what to do + explicitly whether saved. "QC" for checks; "QATrack+" with plus. Canadian spelling in new text (colour, behaviour), match existing file. No emoji, no "!", no marketing. All strings {% trans %}/_(); labels wrap not truncate (translations longer); footers/strips flex-wrap.

## ICONS (FA 4.7 only, <i class="fa fa-x">, prefer -o)
section headers: fa-info-circle Details (section slug "occurrence", box-primary), fa-tags Fault Types, fa-wrench Related Service Events, fa-paperclip Attachments, fa-history Record, fa-commenting-o Comments. actions: fa-pencil edit, fa-trash-o remove/delete, fa-check save/saved/reviewed, fa-undo unacknowledge, fa-check-square-o acknowledge, fa-plus-circle add (status-ok, 16px), fa-search search, fa-upload pending, fa-exclamation-triangle missing/warning, fa-spinner fa-spin busy, fa-file-o/fa-file-image-o file, fa-angle-right breadcrumb sep. nav: fa-lg fa-fw before dropdown items (fa-cubes Choose Unit, fa-pencil-square-o All QC). .fa.{primary,info,danger,warning,success,default} tint. Icon-only btn: title required; add aria-label.
LOGO: only mark = qatrack_core/static/qatrack_core/img/apple-touch-icon.png 114×114 PNG, cyan glowing "Q+" on white; no vector; don't recolour/upscale/put on dark. favicon.ico same dir. reports/static/reports/img/logo.png = Tux test fixture, NOT brand. Header = text wordmark.

## COMPONENTS (templates: qatrack/faults/templates/faults/…)
SectionBox sections/_section_box.html. ctx: section(slug; id fault-section-<section>), title, icon, read_template, edit_template, opt box_class(=box-info), count(→label-default), no_pad(adds .no-pad; ⚠ no rule removes .box-body pad 10 — only .no-pad>.fl-errors is styled), multipart(hx-encoding multipart/form-data), picker_template(foot left), readonly(hide pencil). root div.box.{box_class}.fl-sec[data-editing=0|1][hx-target=this][hx-swap=outerHTML]. header .box-header.with-border > i.fa(18px lh1 mr4; non-.fl-sec boxes e.g. Record/Comments keep AdminLTE mr5) + h3.box-title + [label(ml6 in .fl-sec only)] + .box-tools(flex gap6 top7){i.fa-spinner.fa-spin.fl-spin, [span.fl-saved(inline-flex center gap5 12 600 status-ok) fa-check "Saved"], perm faults.change_fault&&!readonly: editing? span.fl-editing-tag "Editing" : button.tl-iconbtn[title=Edit][hx-get=fault_section_edit][hx-indicator=#box] fa-pencil}. read: .box-body.fl-body[.no-pad]. edit: form[hx-post=fault_section_edit][hx-indicator] csrf > .box-body.fl-body > _form_errors + edit_template; .tl-group-foot(flex center wrap gap8 pad 9 12, border-top 1px surface-subtle, bg surface-foot; .btn nowrap flex none){picker, span.spacer, btn-default btn-sm btn-flat Cancel hx-get=fault_section_detail, submit btn-primary btn-sm btn-flat fa-check Save}. states: editing → shadow-editing ring; .htmx-request → .fl-spin inline-block, .fl-body opacity .45 + pointer-events none (transition .15s); saved → .fl-saved fades (flfade 2s ease forwards: opaque to 70% then 0); 422 → edit box w/ errors. Layout .fl-layout grid 2×minmax(0,1fr) gap16 align start; children (_fault_details.html, unstyled wrappers): div.fl-main{Details(occurrence, box-primary), Record, Attachments(count, multipart)} + aside.fl-side{Fault Types(count, no_pad, picker), Related Service Events(count, no_pad, picker)}; other sections default box-info; .fl-full span all, min-w0; .fl-rule(hr) border 0 + border-top 2px #d2d6de, m 4 0 0, w100%. One form per section; no nesting; cross-box effects via hx-swap-oob, never reload.
Button: .btn-primary(primary,W) main action once per view/section | .btn-default(surface-subtle,text) cancel/secondary | .btn-info(info) filters | .btn-warning(status-tolerance) reverse state e.g. Unacknowledge | .btn-danger-ghost(W bg, danger-deep; border renders transparent — see danger-ghost-border; hover/focus danger-ghost-bg) in-section Delete → confirm page | .btn-success/.btn-danger AdminLTE solids (avoid new: contrast). In sections ALWAYS btn btn-sm btn-flat (12px, pad 5 10, lh1.5, r0; shadow-control still applies). Every .btn: border 1px transparent!important (variant border colours never show), shadow-control!important, focus border link. Non-flat .btn 14px pad 6 12 r3. Leading icon optional.
IconButton .tl-iconbtn 24×24, no border/bg, fg text-faint, r3, 13px, lh24; hover bg surface-iconbtn-hover fg #555; .danger rests #b94a48 on fault pages (sl.css .danger), hover bg danger-ghost-bg fg status-action. Row actions in td.tl-c-act (60, right, nowrap). title+aria-label. Not sole path to important action (⚠ rest colour).
StatusLabel .label (pad .2em .6em .3em, 75%, 600, lh1, W, r2): QC .ok/.tolerance/.action/.no_tol/.not_done (qa.css bg only; all W fg) w/ short names; review _fault_review_status.html span#fault-review-status[hx-swap-oob when oob] > .label.service-event-status-label.fl-status-ok "Reviewed" | .fl-status-unrev "Unreviewed"; service status same class + inline border-color; count .label-default after box title (ml 6 in .fl-sec; Comments: 0, space-separated); .fl-new (10px 700 upper .04em W on status-ok r3 pad 2 6 ml2) beside new fault type; .fl-code-chip (inline-flex mono 11 700 text-code-chip bg surface-code border-code r3 pad 1 6 m 0 4 2 0).
RecordReview _fault_record.html #fault-section-record .box.box-info, fa-history "Record". dl.dl-horizontal.tight: Created (user<br>.fl-meta datetime), Last Modified (sections/_last_modified.html; oob variant _last_modified_oob.html). .fl-rec-review flex center space-between gap10 wrap mt10 pt10 border-top surface-subtle: .fl-rec-status(baseline gap10 13px nowrap){.fl-rec-label "Review Status", reviewed? .fl-rec-ok(600 status-ok) fa-check "Reviewed" : .fl-unrev(600 unreviewed) "Unreviewed"}; !readonly → .fl-rec-actions(flex gap6 flex-wrap:nowrap; .btn nowrap; form m0): perm delete_fault a.btn-danger-ghost.btn-sm.btn-flat fa-trash-o Delete → fault_delete (title explains redirect); perm can_review form#review-form hx-post=fault_review hx-target=#fault-section-record hx-swap=outerHTML: reviewed instance? btn-warning fa-undo "Unacknowledge This Fault" : btn-primary fa-check-square-o "Acknowledge This Fault". Response also oob header status (oob_status).
DataTable .tl-table (w100 collapse) in no_pad section. th: left, pad 7 10, border-bottom 2px border, eyebrow, text-meta, nowrap. td pad 8 10, border-top 1px surface-subtle, valign top. tr:hover surface-hover. SE table sections/_se_table.html cols ID|Status|Date|Problem description|[act]; row _se_row.html: td.fl-se-id a→sl_details <b>#id</b> (+hidden fault-related_service_events when editing), td.fl-se-status service label inline border-color, td.fl-se-date.fl-meta date, td .fl-desc problem, editing td.tl-c-act danger iconbtn data-fl-remove-row. Fault type row _fault_type_row.html: .fl-ft-code(flex center wrap gap4){a.fl-code→fault_type_details target=_blank | span.fl-code, [.fl-new "New"]}, .fl-desc(13 text-desc mt2) (empty → <em>No description available</em>); desc edit (perm change_faulttype or row.is_new) textarea.tl-desc-edit + .fl-desc-actions{btn-primary btn-sm btn-flat "Save description" (existing: hx-post fault_type_edit_description hx-target closest tr), btn-default "Cancel"}; new type desc sent w/ section Save. Empty → div.tl-empty (pad 18 14 center text-faint 13). Full sortable lists use django-listable/DataTables (table-hover table-condensed table-custom-listable), not this.
DescriptionList dl.dl-horizontal (m0 in .fl-layout; bootstrap mb20 elsewhere): dt float left w130 right-aligned text-label 600 pad 3 0 white-space normal (wrap; translations); dd ml146 pad 3 0 min-h 1.5em; bootstrap dd clearfix clears the dt float → row pitch 29 (not 26). .tight 96/108. Empty value → span.text-muted "Not specified" (never blank/dash). Link values that lead somewhere, with title (unit → fault_list_by_unit "Click to view all faults on this unit"). Details read (_section_occurrence_read.html): Occurred, Site (or "Other"), Unit, Modality / Beam.
Picker sections/_fault_type_picker.html, _se_picker.html. .fl-picker(relative) > .tl-search(flex gap6 border r2 pad 5 9 W shadow-inline-input){fa-search, input[type=search][name=q][autocomplete=off] 13px no border/outline w100% pad0 (not .form-control → no shadow), hx-get=picker url, hx-trigger="input changed delay:250ms, focus", hx-include=existing rows' hidden inputs (excluded from results), hx-sync="this:replace", hx-target="next .fl-results", hx-swap=innerHTML, hx-indicator="closest .fl-picker"} + div.fl-results (abs, bottom calc(100%+4px) = opens UPWARD, z50, W, border-popover, shadow-popover, r3, pad6, col gap4, max-h300 scroll, :empty hidden). results (_fault_type_picker_results.html): create_code? first button.tl-pick-item "Create “{code}”"/"New fault type, created when you save"; each button.tl-pick-item[hx-get=…_picker_row?code=][hx-target=#fault-type-rows][hx-swap=beforeend]{.tl-pick-main(col gap2){.tl-pick-name(600 text 13)[+.tl-mono for codes], .tl-pick-sub(12 text-meta ellipsis 1 line)}, fa-plus-circle(16 status-ok flex none)}; none → .tl-pick-hint(12 text-faint pad 4 6) "No matches." Item: flex space-between gap10, border 1px surface-subtle, W, r3, pad 7 10; hover/focus surface-hover + border, no outline. Placeholder states target+min length "Search fault types (2+ characters)…".
FormField .tl-form grid auto-fit minmax(220px,1fr) gap 12 16. div.tl-field col gap4 m0 min-w0 (weight normal): label caption 13 600 text-label m0 [+ <em>*</em> required, status-action, normal style] → .form-control (h30, r0, border #d2d6de, focus link, shadow-control) → span.help 12 600 text-faint (rule .tl-field>span,.tl-field>label = 13/600/#555 m0 hits every direct span; .help overrides size+colour only) → ul.errorlist 12 status-action no bullets. Section errors ul.fl-errors (status-action, mb8; .no-pad> pad 8 12 0) via sections/_form_errors.html. Long text textarea.tl-desc-edit (inline-block (textarea default → ~5px baseline gap below), w100%, border 1px border, r2, pad 5 7, 13, lh1.5, text-label, resize vertical, shadow-inline-input, min-h52, focus border link). Essential info in caption not help (⚠ help colour).
AttachmentChip sections/_attachment_chip.html, _section_attachments_{read,edit}.html. .tle-attach col gap6 stretch. .tle-attach-item flex center gap7 max-w100%, surface-chip, border-chip, r3, pad 5 6 5 9, 12px, text-label, icon slate; saved: fa-file-image-o|fa-file-o + a.tle-attach-name(flex1 min-w0 600 ellipsis nowrap, colour inherit = text-label)→url _blank + .tle-attach-size(11 text-faint nowrap, filesizeformat) + editing button.tle-attach-x(×, no border/bg, chip-remove, 16 lh1 pad 0 2, hover danger-deep)[data-fl-attach-remove]; missing (!file_exists) .fl-missing title "File missing from server" fa-exclamation-triangle, name struck, fg/icon danger-deep; pending (<template data-fl-pending-template>) .fl-pending fa-upload icon link, size text "pending". Add: label.tle-attach-add (inline-flex self-start center gap6 m0, 1px dashed border-dashed, r3, pad 6 11, 12 600 text-meta, W; hover border+fg link) fa-paperclip "Browse…" wrapping input[type=file][name=fault-attachments][multiple].fl-file-input (hidden). Removal only marks: ids → hidden fault-attachments_delete_ids; deleted on Save. Section needs multipart.
PageHeader fault_details.html inside .max-width-lg: .fl-page-head(mb15) h1(22 400 text flex center gap10 wrap){"Fault ID {id}", small(14/1 400 #999) unit, _fault_review_status.html} + ol.fl-breadcrumb(flex wrap center gap8 m 6 0 0 pad0 12px text-crumb no list; links link){a Faults, fa-angle-right, a unit→fault_list_by_unit, fa-angle-right, #id}. Then .fl-layout: sections, hr.fl-full.fl-rule, #box-comments.box.fl-full (fa-commenting-o "Comments" + label-default count).
MainHeader site_base.html header.main-header (h50, chrome-bg, shadow-header, max-h50) > nav.navbar.navbar-static-top > .navbar-header a.logo(w230; .logo-mini/.logo-lg) + ul.nav.navbar-nav.main-nav dropdowns (Perform QC, Review Data, Service Log, Faults…; perm-gated — never show items that 403). Desktop ≥768: dropdowns open on hover. Hover/open item: W bg, #000 fg, side borders chrome-bg. .dropdown-menu r0, border-top 0, mt0, border #bbb, shadow-dropdown; items li>a (pad 3 20, lh20, #777, nowrap) > i.fa.fa-lg.fa-fw mr10 + text; li.nav-header captions pad 3 15 (li>div rule is legacy); li.divider #eee (AdminLTE .dropdown-menu>.divider, all widths; bootstrap #e5e5e5 overridden). a.dropdown-toggle: 1px transparent side borders at rest, + span.caret. Mobile ≤767: open dropdown W, items #000, hover #e1e3e9, divider #eee. .navbar-toggle chrome-bg r0, hover W/#000. user menu: div.custom-nav(abs top0 right0 h50 chrome-bg W; a W) > form#lang-switcher-form(inline-block mr10) > div.nav-button.dropdown#lang-dropdown > a.dropdown-toggle{fa-globe fa-fw LANG caret} + .dropdown-menu (opens on hover), then div#control-sidebar-btn.nav-button "{username} :: fa-gears fa-fw". .nav-button: float right, pad 10, h50, lh30, valign middle; hover W/#000. #control-sidebar-btn overrides: pad 15 10, h auto, lh20, min-w75, center.
Other AdminLTE: .box (W, border-top 3px border, r0 override, mb20, shadow-box); .box-header pad10 fg #444, .with-border border-bottom 1px surface-subtle; .box-tools abs r10 t5; .box-body pad10; .box-small m4/header pad5/title 15. .alert r0 pad 8 20 m0. .callout-custom borders #d2d6de (links link/hover link-hover). .help-block italic 12. .text-display border #ddd mb20 pad10 bg #f4f4f4. .field-group-title #777 italic center mb10 border-bottom #ddd. .subheading-divider m 5 -10, pad 0 5, 600 15, border-bottom #e2e6ee. .timeline-custom item r0 no shadow; time w140. .loading-modal fixed z1000 rgba(255,255,255,.6). input[type=number] no spinners. .box-comments W (fault page: #box-comments .box-body > div#comments.box-comments; .box-footer.box-comments adds border-top 1px surface-subtle). .box-comment pad 8 (first pt0) mb3 surface-comment, border-bottom 1px #eee (last 0), hover #f2f2f2 > .comment-text(m0, #555) > span.username(block 600 #444 + span.text-muted.pull-right 12 400 date (AdminLTE .box-comments .text-muted; not the username's 600)) + span.comment(pre-line). .err-comment bg comment-error (hover #d86268); W only on .username/.comment (box fg stays).

## A11Y — contrast to fix (now → smallest same-hue pass; proposals, discuss first)
text-faint #9aa2ae/W 2.58 → #6d7787 4.53
text-meta #8a929e/W 3.14 → #6e7785 4.53
text-crumb #97a0b3/page-bg 2.30 → #616d85 4.55
link #3c8dbc/W 3.67 → #357da7 4.52 (W) | #317399 4.54 (also page-bg)
status-ok text #00a65a/W 3.18 → #008749 4.60
unreviewed #b0761a/W 3.85 → #a06c18 4.51
status-action text #dd4b39/W 4.09 → #da3b28 4.53 | reuse danger-deep #c0392b 5.44
text-muted #777/W 4.48 → #767676 4.54
chrome-text-sub #8aa4af/#2c3b41 4.43 → #8eaab5 4.74
W on status-tolerance 2.19 → #000 text 9.58 (as .not_done)
W on status-no-tol 2.15 → #000 9.79
W on status-ok 3.18 → fill #008749 4.60 | #000 6.60
W on status-action 4.09 → fill #d73925 4.67 (= existing hover)
W on comment-error #e76167 3.33 → #000 6.30
W on status-not-done 1.93 → #000 10.91
Also ⚠: #4b646f/#1a2226 2.58 (sidebar header), #999/W 2.85 (nav-header, h1 small), border #d2d6de/W 1.46 (decorative only).
Caveats: status colours are per-site DB values → fixing defaults doesn't fix sites; border+black-text pattern works for any colour. Darken, never change hue (staff recognition). AdminLTE colours affect every page.
