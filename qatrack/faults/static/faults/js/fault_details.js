/*
 * Fault details page.
 *
 * The server renders every section and htmx swaps them in, so this file only
 * covers what happens in the browser before a section is saved: removing
 * rows, editing a new fault type's description, attachment chips, and closing
 * picker results. Listeners sit on the document so they keep working after
 * htmx replaces a section. Text from the page is only ever set with
 * textContent, never assembled into HTML.
 */
(function () {
    "use strict";

    function sectionOf(el) {
        return el.closest(".fl-sec");
    }

    // Keep the count in a section's header in step with its rows or chips.
    function refreshCount(section) {
        if (!section) {
            return;
        }
        var label = section.querySelector("[data-fl-count]");
        if (!label) {
            return;
        }
        var rows = section.querySelector("tbody");
        if (rows) {
            label.textContent = rows.querySelectorAll("tr").length;
            return;
        }
        label.textContent = section.querySelectorAll(".tle-attach-item:not(.fl-removed)").length;
    }

    function closePickers() {
        document.querySelectorAll(".fl-results").forEach(function (results) {
            results.innerHTML = "";
        });
    }

    /* Fault type descriptions */

    function showDescriptionEditor(row, show) {
        var editor = row.querySelector("[data-fl-desc-editor]");
        var display = row.querySelector("[data-fl-desc-display]");
        var pencil = row.querySelector("[data-fl-desc-edit]");
        if (!editor) {
            return;
        }
        editor.hidden = !show;
        display.hidden = show;
        if (pencil) {
            pencil.hidden = show;
        }
        if (show) {
            editor.querySelector("textarea").focus();
        }
    }

    function showDescription(display, text) {
        display.textContent = "";
        if (text) {
            display.textContent = text;
        } else {
            var empty = document.createElement("em");
            empty.textContent = display.getAttribute("data-empty-text");
            display.appendChild(empty);
        }
    }

    /* Attachments */

    // Files picked so far, per file input. The input itself only remembers the
    // last selection, so they're gathered here and written back to it.
    var pendingFiles = new WeakMap();

    function renderPending(input) {
        var container = input.closest("[data-fl-attach]");
        var list = container.querySelector("[data-fl-attach-pending]");
        var template = sectionOf(input).querySelector("[data-fl-pending-template]");
        var files = pendingFiles.get(input);

        list.textContent = "";
        Array.prototype.forEach.call(files.files, function (file, index) {
            var chip = template.content.firstElementChild.cloneNode(true);
            chip.querySelector(".tle-attach-name").textContent = file.name;
            chip.querySelector("[data-fl-pending-remove]").setAttribute("data-index", index);
            list.appendChild(chip);
        });
        input.files = files.files;
        refreshCount(sectionOf(input));
    }

    document.addEventListener("change", function (evt) {
        var input = evt.target.closest("[data-fl-attach-input]");
        if (!input) {
            return;
        }
        var files = pendingFiles.get(input) || new DataTransfer();
        Array.prototype.forEach.call(input.files, function (file) {
            files.items.add(file);
        });
        pendingFiles.set(input, files);
        renderPending(input);
    });

    /* Clicks */

    document.addEventListener("click", function (evt) {
        var target = evt.target;

        if (!target.closest(".fl-picker")) {
            closePickers();
        }

        var button = target.closest("[data-fl-remove-row]");
        if (button) {
            var section = sectionOf(button);
            button.closest("tr").remove();
            refreshCount(section);
            return;
        }

        button = target.closest("[data-fl-desc-edit]");
        if (button) {
            showDescriptionEditor(button.closest("tr"), true);
            return;
        }

        button = target.closest("[data-fl-desc-cancel]");
        if (button) {
            var row = button.closest("tr");
            var textarea = row.querySelector("[data-fl-desc-editor] textarea");
            textarea.value = textarea.defaultValue;
            showDescriptionEditor(row, false);
            return;
        }

        // A new fault type's description is kept in its textarea and sent
        // with the section's Save, when the type is created.
        button = target.closest("[data-fl-desc-keep]");
        if (button) {
            var newRow = button.closest("tr");
            var newText = newRow.querySelector("[data-fl-desc-editor] textarea");
            newText.value = newText.value.trim();
            newText.defaultValue = newText.value;
            showDescription(newRow.querySelector("[data-fl-desc-display]"), newText.value);
            showDescriptionEditor(newRow, false);
            return;
        }

        button = target.closest("[data-fl-attach-remove]");
        if (button) {
            var chip = button.closest(".tle-attach-item");
            var form = button.closest("form");
            var deletes = form.querySelector("[data-fl-attach-deletes]");
            var ids = deletes.value ? deletes.value.split(",") : [];
            ids.push(chip.getAttribute("data-attach-id"));
            deletes.value = ids.join(",");
            chip.classList.add("fl-removed");
            refreshCount(sectionOf(button));
            return;
        }

        button = target.closest("[data-fl-pending-remove]");
        if (button) {
            var input = button.closest("[data-fl-attach]").querySelector("[data-fl-attach-input]");
            var current = pendingFiles.get(input);
            var remaining = new DataTransfer();
            var skip = parseInt(button.getAttribute("data-index"), 10);
            Array.prototype.forEach.call(current.files, function (file, index) {
                if (index !== skip) {
                    remaining.items.add(file);
                }
            });
            pendingFiles.set(input, remaining);
            renderPending(input);
        }
    });

    /* Keyboard */

    document.addEventListener("keydown", function (evt) {
        if (evt.key === "Escape") {
            closePickers();
        }
        // Enter in a picker's search box would otherwise submit the section.
        if (evt.key === "Enter" && evt.target.closest("[data-fl-picker]")) {
            evt.preventDefault();
        }
    });

    /* After a row is added from a picker */

    document.body.addEventListener("htmx:afterRequest", function (evt) {
        var elt = evt.detail.elt;
        if (!evt.detail.successful || !elt.classList || !elt.classList.contains("tl-pick-item")) {
            return;
        }
        var picker = elt.closest(".fl-picker");
        var section = sectionOf(elt);
        if (picker) {
            picker.querySelector("[data-fl-picker]").value = "";
        }
        closePickers();
        refreshCount(section);
    });
}());
