/* Test List Builder — pass 1 progressive enhancement.
 *
 * Change form: relocate the live Django form controls into the styled Details
 * card (moving nodes, never cloning, so POST names/ids, slug prepopulation and
 * validation keep working) and wire the description HTML preview toggle.
 *
 * Changelist: make whole rows clickable and set the search placeholder.
 *
 * Vanilla JS, no build step. Both pages share this file (loaded via
 * TestListAdmin.Media); each enhancer no-ops when its markup is absent.
 */
(function () {
    "use strict";

    function buildDetailsCard() {
        var card = document.getElementById("tl-details-card");
        if (!card) {
            return;
        }

        // Move a field's live input (and any error list) into its card slot.
        // Errors are placed above the control, per spec.
        function relocate(fieldName, slotName) {
            var input = document.getElementById("id_" + fieldName);
            var slot = card.querySelector('[data-slot="' + slotName + '"]');
            if (!input || !slot) {
                return null;
            }
            var row = input.closest(".form-row") || input.parentNode;
            if (row) {
                row.querySelectorAll(".errorlist").forEach(function (err) {
                    slot.appendChild(err);
                });
            }
            slot.appendChild(input);
            return input;
        }

        relocate("name", "name");
        relocate("slug", "slug");
        var desc = relocate("description", "description");
        relocate("warning_message", "warning");
        var js = relocate("javascript", "javascript");

        // Compact the textareas to the mock's row counts.
        if (desc) {
            desc.setAttribute("rows", "2");
            desc.classList.remove("vLargeTextField");
        }
        if (js) {
            js.setAttribute("rows", "3");
            js.classList.remove("vLargeTextField");
            js.setAttribute("spellcheck", "false");
            if (!js.value) {
                js.setAttribute(
                    "placeholder",
                    "// Custom JS for this test list — e.g. show a hint"
                );
            }
        }

        // Surface the read-only ID in the card header ("ID: 142").
        var idBadge = document.getElementById("tl-details-id");
        if (idBadge) {
            var idNode = document.querySelector("#tl-source-fields .field-id .readonly");
            var idText = idNode ? idNode.textContent.trim() : "";
            if (idText && /\d/.test(idText)) {
                idBadge.textContent = "ID: " + idText;
                idBadge.hidden = false;
            }
        }

        // Description live HTML preview. When enabled the textarea stays
        // visible and editable, with the preview shown beneath it and updated
        // on every keystroke; toggling off hides the preview again.
        var toggle = card.querySelector("[data-desc-toggle]");
        var preview = card.querySelector("[data-desc-preview]");
        if (toggle && preview && desc) {
            // keep the preview directly below the relocated textarea
            desc.parentNode.appendChild(preview);
            var emptyMsg =
                '<span class="tl-htmlpreview-empty">Nothing to preview — ' +
                "write a description to see how the markup renders.</span>";
            var render = function () {
                var val = (desc.value || "").trim();
                preview.innerHTML = val ? val : emptyMsg;
            };
            var setEnabled = function (on) {
                preview.hidden = !on;
                toggle.classList.toggle("on", on);
                toggle.innerHTML = on
                    ? '<i class="fa fa-eye-slash"></i> Hide preview'
                    : '<i class="fa fa-eye"></i> Preview';
                if (on) {
                    render();
                }
            };
            toggle.addEventListener("click", function (e) {
                e.preventDefault();
                setEnabled(preview.hidden); // hidden now -> enable, else disable
            });
            desc.addEventListener("input", function () {
                if (!preview.hidden) {
                    render();
                }
            });
        }
    }

    function initChangelist() {
        var table = document.getElementById("result_list");
        if (!table) {
            return;
        }

        var search = document.getElementById("searchbar");
        if (search && !search.getAttribute("placeholder")) {
            search.setAttribute("placeholder", "Search name, slug or tags…");
        }

        table.querySelectorAll("tbody tr").forEach(function (tr) {
            tr.addEventListener("click", function (e) {
                // Let real links, the row checkbox, and text selection behave.
                if (
                    e.target.closest("a") ||
                    e.target.closest("input") ||
                    e.target.closest("label") ||
                    window.getSelection().toString()
                ) {
                    return;
                }
                var link = tr.querySelector("a.tl-editlink") || tr.querySelector("a.tl-cell-name");
                if (link) {
                    window.location = link.href;
                }
            });
        });
    }

    document.addEventListener("DOMContentLoaded", function () {
        buildDetailsCard();
        initChangelist();
    });
})();
