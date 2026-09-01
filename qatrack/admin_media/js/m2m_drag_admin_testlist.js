/**
 * Test List Builder — Drag-and-drop reordering, HTMX interactions,
 * and Django formset synchronization for Tests & Sublists.
 */
(function () {
  "use strict";

  if (window.__TL_BUILDER_INITIALIZED__) {
    return;
  }
  window.__TL_BUILDER_INITIALIZED__ = true;

  var activeSwapCard = null;

  function sortBuilderItemsByOrder() {
    var tbody = document.getElementById("tl-tests-tbody");
    if (!tbody) { return; }
    var rows = Array.from(tbody.querySelectorAll("tr.tl-member-item"));
    if (rows.length <= 1) { return; }

    rows.sort(function (a, b) {
      var orderA = parseInt(a.getAttribute("data-order"), 10);
      if (isNaN(orderA)) {
        var inputA = a.querySelector(".tl-order-input, .tl-sublist-order-input");
        orderA = inputA && inputA.value !== "" ? parseInt(inputA.value, 10) : 9999;
      }
      var orderB = parseInt(b.getAttribute("data-order"), 10);
      if (isNaN(orderB)) {
        var inputB = b.querySelector(".tl-order-input, .tl-sublist-order-input");
        orderB = inputB && inputB.value !== "" ? parseInt(inputB.value, 10) : 9999;
      }
      return orderA - orderB;
    });

    rows.forEach(function (r) {
      tbody.appendChild(r);
    });
  }

  function updateCounts() {
    var rows = document.querySelectorAll("#tl-tests-tbody tr.tl-member-item");
    var visibleDirectCount = 0;
    var visibleSublistsCount = 0;
    var sublistTestsCount = 0;

    rows.forEach(function (r) {
      var del = r.querySelector("input[name$='-DELETE']");
      var isDel = del && (del.checked || del.value === "true");
      var isHidden = r.style.display === "none";
      if (!isDel && !isHidden) {
        if (r.classList.contains("tl-test-row")) {
          visibleDirectCount++;
        } else if (r.classList.contains("tl-sublist-row")) {
          visibleSublistsCount++;
          var subRows = r.querySelectorAll("tbody tr.tl-sublist-test-row");
          sublistTestsCount += subRows.length;
        }
      }
    });

    var totalTests = visibleDirectCount + sublistTestsCount;
    var totalSections = visibleSublistsCount + (visibleDirectCount > 0 ? 1 : 0);

    var badge = document.getElementById("tl-tests-count");
    if (badge) { badge.textContent = visibleDirectCount; }
    var emptyMsg = document.getElementById("tl-empty-tests-msg");
    if (emptyMsg) {
      emptyMsg.style.display = (visibleDirectCount + visibleSublistsCount) === 0 ? "block" : "none";
    }

    var headerCounts = document.getElementById("tl-header-counts");
    if (headerCounts) {
      var tStr = totalTests === 1 ? "1 test" : (totalTests + " tests");
      var sStr = totalSections === 1 ? "1 section" : (totalSections + " sections");
      headerCounts.innerHTML = '<span>' + tStr + '</span> &middot; <span>' + sStr + '</span>';
    }
  }

  function syncOrder() {
    var order = 0;
    var rows = document.querySelectorAll("#tl-tests-tbody tr.tl-member-item");
    rows.forEach(function (r) {
      var del = r.querySelector("input[name$='-DELETE']");
      var isDel = del && (del.checked || del.value === "true");
      var isHidden = r.style.display === "none";

      var orderInput = r.querySelector(".tl-order-input, .tl-sublist-order-input");
      if (orderInput) {
        if (!isDel && !isHidden) {
          orderInput.value = order;
          r.setAttribute("data-order", order);
          order++;
        } else {
          orderInput.value = "";
        }
      }
    });

    updateCounts();
  }

  function openSearchModal(mode, swapCard) {
    activeSwapCard = swapCard || null;
    var modal = document.getElementById("tl-search-modal");
    if (!modal) { return; }

    var title = document.getElementById("tl-search-title-text");
    var input = document.getElementById("tl-search-input");
    var resultsBox = document.getElementById("tl-search-results-box");

    var testsCard = document.getElementById("tl-tests-card");
    var originalId = testsCard ? (testsCard.getAttribute("data-original-id") || "") : "";

    var url = "";
    if (mode === "test") {
      if (title) { title.textContent = "Select Test to Add"; }
      if (input) {
        input.placeholder = "Search by test name, macro slug or category…";
        url = "/admin/qa/testlist/search-tests/";
        input.setAttribute("hx-get", url);
        input.value = "";
      }
    } else {
      if (title) { title.textContent = activeSwapCard ? "Change Sublist" : "Select Sublist to Add"; }
      if (input) {
        input.placeholder = "Search available test lists…";
        url = "/admin/qa/testlist/search-sublists/" + (originalId ? "?current_id=" + encodeURIComponent(originalId) : "");
        input.setAttribute("hx-get", url);
        input.value = "";
      }
    }

    modal.hidden = false;
    if (resultsBox) {
      resultsBox.innerHTML = '<div class="tl-search-initial-hint"><i class="fa fa-spinner fa-spin"></i> Loading…</div>';
      fetch(url)
        .then(function (res) { return res.text(); })
        .then(function (html) {
          resultsBox.innerHTML = html;
          if (window.htmx) { htmx.process(resultsBox); }
        })
        .catch(function () {
          resultsBox.innerHTML = '<div class="tl-search-no-results">Error loading items.</div>';
        });
    }

    if (input) {
      if (window.htmx) { htmx.process(input); }
      setTimeout(function () { input.focus(); }, 60);
    }
  }

  function addTestRow(testId) {
    var totalFormsInput = document.getElementById("id_testlistmembership_set-TOTAL_FORMS");
    var currentIndex = totalFormsInput ? (parseInt(totalFormsInput.value, 10) || 0) : 0;
    var testsCard = document.getElementById("tl-tests-card");
    var originalId = testsCard ? (testsCard.getAttribute("data-original-id") || "") : "";

    var url = "/admin/qa/testlist/add-test-row/?test_id=" + encodeURIComponent(testId) +
              "&index=" + currentIndex +
              "&test_list_id=" + encodeURIComponent(originalId);

    fetch(url)
      .then(function (res) { return res.text(); })
      .then(function (html) {
        var tbody = document.getElementById("tl-tests-tbody");
        if (!tbody) { return; }
        var temp = document.createElement("tbody");
        temp.innerHTML = html.trim();
        var newRow = temp.firstElementChild;
        if (newRow) {
          tbody.appendChild(newRow);
          if (totalFormsInput) { totalFormsInput.value = currentIndex + 1; }
          if (window.htmx) { htmx.process(newRow); }
          syncOrder();
          initSortables();
        }
      });
  }

  function addSublistCard(childId) {
    if (activeSwapCard) {
      var card = activeSwapCard;
      var index = card.getAttribute("data-index") || "0";
      var testsCard = document.getElementById("tl-tests-card");
      var originalId = testsCard ? (testsCard.getAttribute("data-original-id") || "") : "";
      var url = "/admin/qa/testlist/add-sublist-card/?child_id=" + encodeURIComponent(childId) +
                "&index=" + index +
                "&parent_id=" + encodeURIComponent(originalId);
      fetch(url)
        .then(function (res) { return res.text(); })
        .then(function (html) {
          var temp = document.createElement("tbody");
          temp.innerHTML = html.trim();
          var newCard = temp.firstElementChild;
          if (newCard && card.parentNode) {
            card.parentNode.replaceChild(newCard, card);
            if (window.htmx) { htmx.process(newCard); }
            activeSwapCard = null;
            syncOrder();
            initSortables();
          }
        });
      return;
    }

    var totalFormsInput = document.getElementById("id_children-TOTAL_FORMS");
    var currentIndex = totalFormsInput ? (parseInt(totalFormsInput.value, 10) || 0) : 0;
    var testsCard = document.getElementById("tl-tests-card");
    var originalId = testsCard ? (testsCard.getAttribute("data-original-id") || "") : "";

    var url = "/admin/qa/testlist/add-sublist-card/?child_id=" + encodeURIComponent(childId) +
              "&index=" + currentIndex +
              "&parent_id=" + encodeURIComponent(originalId);

    fetch(url)
      .then(function (res) { return res.text(); })
      .then(function (html) {
        var tbody = document.getElementById("tl-tests-tbody");
        if (!tbody) { return; }
        var temp = document.createElement("tbody");
        temp.innerHTML = html.trim();
        var newCard = temp.firstElementChild;
        if (newCard) {
          tbody.appendChild(newCard);
          if (totalFormsInput) { totalFormsInput.value = currentIndex + 1; }
          if (window.htmx) { htmx.process(newCard); }
          syncOrder();
          initSortables();
        }
      });
  }

  // Drag-and-drop sortable support (HTML5 native + jQuery UI if available)
  function initSortables() {
    var $ = window.django && window.django.jQuery ? window.django.jQuery : (window.jQuery || window.$);
    if ($ && $.fn && $.fn.sortable) {
      try {
        $("#tl-tests-tbody").sortable({
          handle: ".tl-drag-handle",
          items: "> tr.tl-member-item",
          axis: "y",
          helper: function (e, tr) {
            var $originals = tr.children();
            var $helper = tr.clone();
            $helper.children().each(function (index) {
              $(this).width($originals.eq(index).width());
            });
            return $helper;
          },
          start: function (e, ui) {
            ui.placeholder.height(ui.item.height());
          },
          update: function () {
            syncOrder();
          }
        });
      } catch (err) {}
    }

    // HTML5 drag-and-drop fallback
    var tbody = document.getElementById("tl-tests-tbody");
    if (tbody) {
      tbody.querySelectorAll("tr.tl-member-item").forEach(function (row) {
        var handle = row.querySelector(".tl-drag-handle");
        if (handle && !row.hasAttribute("data-dnd-init")) {
          row.setAttribute("data-dnd-init", "true");
          handle.setAttribute("draggable", "true");
          handle.addEventListener("dragstart", function (e) {
            e.dataTransfer.setData("text/plain", "");
            row.classList.add("tl-dragging");
            window._tlDraggedRow = row;
          });
          handle.addEventListener("dragend", function () {
            row.classList.remove("tl-dragging");
            window._tlDraggedRow = null;
            syncOrder();
          });
          row.addEventListener("dragover", function (e) {
            e.preventDefault();
            var dragged = window._tlDraggedRow;
            if (dragged && dragged !== row && row.parentNode === tbody) {
              var rect = row.getBoundingClientRect();
              var mid = rect.top + rect.height / 2;
              if (e.clientY < mid) {
                tbody.insertBefore(dragged, row);
              } else {
                tbody.insertBefore(dragged, row.nextSibling);
              }
            }
          });
        }
      });
    }
  }

  function initSublistToggles() {
    var toggleAllBtn = document.getElementById("tl-toggle-all-sublists-btn");
    var toggleAllText = document.getElementById("tl-toggle-all-sublists-text");
    if (toggleAllBtn && !toggleAllBtn.hasAttribute("data-init")) {
      toggleAllBtn.setAttribute("data-init", "true");
      toggleAllBtn.addEventListener("click", function (e) {
        e.preventDefault();
        var sublistRows = document.querySelectorAll("#tl-tests-tbody tr.tl-sublist-row");
        if (sublistRows.length === 0) { return; }

        var anyCollapsed = Array.from(sublistRows).some(function (r) {
          return r.classList.contains("collapsed") && r.style.display !== "none";
        });

        sublistRows.forEach(function (r) {
          var body = r.querySelector(".tl-sublist-body");
          var btn = r.querySelector(".tl-sublist-toggle-btn");
          if (anyCollapsed) {
            r.classList.remove("collapsed");
            r.classList.add("expanded");
            if (body) { body.style.display = "block"; }
            if (btn) { btn.setAttribute("aria-expanded", "true"); }
          } else {
            r.classList.remove("expanded");
            r.classList.add("collapsed");
            if (body) { body.style.display = "none"; }
            if (btn) { btn.setAttribute("aria-expanded", "false"); }
          }
        });

        if (toggleAllText) {
          toggleAllText.textContent = anyCollapsed ? "Collapse all" : "Expand all";
        }
        var icon = toggleAllBtn.querySelector("i");
        if (icon) {
          icon.className = anyCollapsed ? "fa fa-compress" : "fa fa-expand";
        }
      });
    }
  }

  document.addEventListener("click", function (e) {
    // Individual Sublist Expand/Collapse toggle
    var toggleBtn = e.target.closest(".tl-sublist-toggle-btn");
    var titleWrap = e.target.closest(".tl-sublist-title-wrap");
    if (toggleBtn || titleWrap) {
      if (e.target.closest("button") && !e.target.closest(".tl-sublist-toggle-btn")) { return; }
      if (e.target.closest("a") || e.target.closest("input")) { return; }

      e.preventDefault();
      var sublistRow = (toggleBtn || titleWrap).closest(".tl-sublist-row");
      if (sublistRow) {
        var isCollapsed = sublistRow.classList.contains("collapsed");
        var body = sublistRow.querySelector(".tl-sublist-body");
        var btn = sublistRow.querySelector(".tl-sublist-toggle-btn");
        if (isCollapsed) {
          sublistRow.classList.remove("collapsed");
          sublistRow.classList.add("expanded");
          if (body) { body.style.display = "block"; }
          if (btn) { btn.setAttribute("aria-expanded", "true"); }
        } else {
          sublistRow.classList.remove("expanded");
          sublistRow.classList.add("collapsed");
          if (body) { body.style.display = "none"; }
          if (btn) { btn.setAttribute("aria-expanded", "false"); }
        }
      }
      return;
    }

    if (e.target.closest("#tl-header-add-test-btn, #tl-add-test-btn")) {
      e.preventDefault();
      openSearchModal("test");
      return;
    }

    if (e.target.closest("#tl-add-sublist-btn")) {
      e.preventDefault();
      openSearchModal("sublist");
      return;
    }

    var changeBtn = e.target.closest(".tl-btn-change-sublist");
    if (changeBtn) {
      e.preventDefault();
      var card = changeBtn.closest(".tl-sublist-card");
      openSearchModal("sublist", card);
      return;
    }

    var testItem = e.target.closest(".tl-search-test-item, .tl-btn-select-test");
    if (testItem) {
      e.preventDefault();
      var row = testItem.closest(".tl-search-test-item");
      var testId = testItem.getAttribute("data-test-id") || (row && row.getAttribute("data-test-id"));
      if (testId) {
        addTestRow(testId);
        var modal = document.getElementById("tl-search-modal");
        if (modal) { modal.hidden = true; }
      }
      return;
    }

    var sublistItem = e.target.closest(".tl-search-sublist-item, .tl-btn-select-sublist");
    if (sublistItem) {
      e.preventDefault();
      var sRow = sublistItem.closest(".tl-search-sublist-item");
      var childId = sublistItem.getAttribute("data-child-id") || (sRow && sRow.getAttribute("data-child-id"));
      if (childId) {
        addSublistCard(childId);
        var sModal = document.getElementById("tl-search-modal");
        if (sModal) { sModal.hidden = true; }
      }
      return;
    }

    var delTestBtn = e.target.closest(".tl-delete-test-btn");
    if (delTestBtn) {
      e.preventDefault();
      var tRow = delTestBtn.closest("tr.tl-test-row");
      if (tRow) {
        var delInput = tRow.querySelector("input[name$='-DELETE']");
        if (delInput) { delInput.checked = true; }
        tRow.style.transition = "opacity 0.2s ease, transform 0.2s ease";
        tRow.style.opacity = "0";
        setTimeout(function () {
          tRow.style.display = "none";
          syncOrder();
        }, 180);
      }
      return;
    }

    var delSubBtn = e.target.closest(".tl-btn-remove-sublist");
    if (delSubBtn) {
      e.preventDefault();
      var sCard = delSubBtn.closest(".tl-sublist-card");
      if (sCard) {
        var sDelInput = sCard.querySelector("input[name$='-DELETE']");
        if (sDelInput) { sDelInput.checked = true; }
        sCard.style.transition = "opacity 0.2s ease, transform 0.2s ease";
        sCard.style.opacity = "0";
        setTimeout(function () {
          sCard.style.display = "none";
          syncOrder();
        }, 180);
      }
      return;
    }

    // Duplicate Test button
    var dupBtn = e.target.closest(".tl-duplicate-test-btn");
    if (dupBtn) {
      e.preventDefault();
      var dRow = dupBtn.closest("tr.tl-test-row");
      var dTestId = dupBtn.getAttribute("data-test-id") || (dRow && dRow.getAttribute("data-test-id"));
      if (!dTestId && dRow) {
        var tInput = dRow.querySelector("input[name$='-test']");
        if (tInput) { dTestId = tInput.value; }
      }
      if (dTestId) {
        var totalFormsInput = document.getElementById("id_testlistmembership_set-TOTAL_FORMS");
        var currentIndex = totalFormsInput ? (parseInt(totalFormsInput.value, 10) || 0) : 0;
        var modalContainer = document.getElementById("tl-modal-container");
        if (modalContainer) {
          fetch("/admin/qa/testlist/duplicate-test/?test_id=" + encodeURIComponent(dTestId) + "&index=" + currentIndex)
            .then(function(res) { return res.text(); })
            .then(function(html) {
              modalContainer.innerHTML = html;
              var dInput = document.getElementById("id_dup_name");
              if (dInput) { dInput.focus(); dInput.select(); }
            })
            .catch(function(err) {
              console.error("Failed to load duplicate modal", err);
            });
        }
      }
      return;
    }

    // Modal close buttons
    if (e.target.matches("[data-search-close]") || e.target.closest("[data-search-close]")) {
      var sModalClose = document.getElementById("tl-search-modal");
      if (sModalClose) { sModalClose.hidden = true; }
    }
    if (e.target.matches("[data-modal-close]") || e.target.closest("[data-modal-close]")) {
      var dModalClose = document.getElementById("tl-desc-modal-backdrop") || document.getElementById("tl-duplicate-modal-backdrop") || e.target.closest(".tl-modal-backdrop");
      if (dModalClose) { dModalClose.remove(); }
    }
    if (e.target.classList && e.target.classList.contains("tl-modal-backdrop")) {
      e.target.hidden = true;
      if (e.target.id === "tl-desc-modal-backdrop" || e.target.id === "tl-duplicate-modal-backdrop") { e.target.remove(); }
    }
  });

  // Duplicate test form submission & normal re-sync on form submission
  document.addEventListener("submit", function (e) {
    if (e.target && e.target.id === "tl-duplicate-test-form") {
      e.preventDefault();
      var form = e.target;
      var submitBtn = document.getElementById("tl-btn-submit-duplicate");
      var errorBox = document.getElementById("tl-dup-error-msg");
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<i class="fa fa-spinner fa-spin"></i> Creating…';
      }
      if (errorBox) { errorBox.style.display = "none"; }

      var formData = new FormData(form);
      var testsCard = document.getElementById("tl-tests-card");
      var origId = testsCard ? (testsCard.getAttribute("data-original-id") || "") : "";
      if (origId) { formData.append("test_list_id", origId); }

      fetch(form.action, {
        method: "POST",
        body: formData,
        headers: { "X-Requested-With": "XMLHttpRequest" }
      })
      .then(function(res) {
        if (!res.ok) {
          return res.text().then(function(text) { throw new Error(text || "Failed to create duplicate test."); });
        }
        return res.text();
      })
      .then(function(rowHtml) {
        var tbody = document.getElementById("tl-tests-tbody");
        if (tbody) {
          var temp = document.createElement("tbody");
          temp.innerHTML = rowHtml.trim();
          var newRow = temp.firstElementChild;
          if (newRow) {
            var sourceId = formData.get("source_test_id");
            var sourceRow = sourceId ? tbody.querySelector("tr.tl-test-row[data-test-id='" + sourceId + "']") : null;
            if (sourceRow && sourceRow.parentNode === tbody) {
              sourceRow.after(newRow);
            } else {
              tbody.appendChild(newRow);
            }
            newRow.style.animation = "tl-pulse-highlight 1.5s ease";
          }
        }
        var totalFormsInput = document.getElementById("id_testlistmembership_set-TOTAL_FORMS");
        if (totalFormsInput) {
          var cur = parseInt(totalFormsInput.value, 10) || 0;
          totalFormsInput.value = cur + 1;
        }
        initSortables();
        syncOrder();
        updateCounts();
        var modalBackdrop = document.getElementById("tl-duplicate-modal-backdrop");
        if (modalBackdrop) { modalBackdrop.remove(); }
      })
      .catch(function(err) {
        if (errorBox) {
          errorBox.textContent = err.message;
          errorBox.style.display = "block";
        } else {
          alert(err.message);
        }
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.innerHTML = '<i class="fa fa-clone"></i> Create & Add Test';
        }
      });
      return;
    }

    if (e.target.matches("form")) {
      syncOrder();
    }
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      var sModalEsc = document.getElementById("tl-search-modal");
      if (sModalEsc && !sModalEsc.hidden) { sModalEsc.hidden = true; }
      var dModalEsc = document.getElementById("tl-desc-modal-backdrop") || document.getElementById("tl-duplicate-modal-backdrop");
      if (dModalEsc) { dModalEsc.remove(); }
    }
  });

  function escapeHtml(text) {
    if (!text) { return ""; }
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function initAttachmentsSection() {
    var fileInput = document.getElementById("id_tl-new-attachments");
    var container = document.getElementById("attachments-editor-container");
    if (!container || !fileInput) { return; }

    var prefix = container.getAttribute("data-prefix") || "attachments_attachment_set";
    var parentId = container.getAttribute("data-parent-id") || "";
    var totalFormsInput = document.getElementById("id_" + prefix + "-TOTAL_FORMS");
    var pendingList = document.getElementById("pending-attachments-list");
    var formsetInputsContainer = document.getElementById("new-attachments-formset-inputs");

    function updateAttachmentCounts() {
      var existingVisible = document.querySelectorAll("#existing-attachments-list .attachment-card:not([style*='display: none'])").length;
      var pendingCount = document.querySelectorAll("#pending-attachments-list .attachment-card").length;
      var total = existingVisible + pendingCount;
      var badge = document.getElementById("tl-attachments-count");
      if (badge) { badge.textContent = total; }
      var emptyMsg = document.getElementById("tl-empty-attachments-msg");
      if (emptyMsg) {
        emptyMsg.style.display = total === 0 ? "block" : "none";
      }
    }

    // Existing attachments deletion
    document.addEventListener("click", function(e) {
      var delBtn = e.target.closest(".btn-delete-existing");
      if (delBtn) {
        e.preventDefault();
        var attachId = delBtn.getAttribute("data-id");
        var card = document.getElementById("existing-attach-" + attachId);
        if (card) {
          card.style.display = "none";
          var delCheckbox = card.querySelector(".attach-delete");
          if (delCheckbox) { delCheckbox.checked = true; }
          updateAttachmentCounts();
        }
      }
    });

    // File input change: add pending attachment cards and Django formset file inputs
    fileInput.addEventListener("change", function () {
      if (!this.files || !this.files.length) { return; }

      var currentTotal = totalFormsInput ? (parseInt(totalFormsInput.value, 10) || 0) : 0;

      Array.from(this.files).forEach(function (file) {
        var newIndex = currentTotal;
        var url = URL.createObjectURL(file);
        var sizeKB = (file.size / 1024).toFixed(1);

        // 1. Create pending visual card matching Fault Logs
        var card = document.createElement("div");
        card.className = "attachment-card pending";
        card.id = "pending-attach-" + newIndex;
        card.innerHTML =
          '<div class="attachment-name">' +
            '<i class="fa fa-upload fa-fw text-info"></i> ' +
            '<strong>' + escapeHtml(file.name) + '</strong> ' +
            '<span class="text-muted">(' + sizeKB + ' KB)</span>' +
            '<input type="text" name="' + prefix + '-' + newIndex + '-comment" placeholder="Add optional comment..." class="tl-pending-comment-input">' +
          '</div>' +
          '<div class="attachment-actions">' +
            '<a href="' + url + '" target="_blank" class="btn btn-default btn-xs margin-right-5" title="Preview"><i class="fa fa-eye"></i></a>' +
            '<button type="button" class="btn btn-danger btn-xs btn-remove-pending" data-index="' + newIndex + '" title="Remove"><i class="fa fa-trash"></i></button>' +
          '</div>';
        pendingList.appendChild(card);

        // 2. Create actual Django formset input with DataTransfer
        var dt = new DataTransfer();
        dt.items.add(file);

        var rowDiv = document.createElement("div");
        rowDiv.id = "formset-row-" + newIndex;

        var input = document.createElement("input");
        input.type = "file";
        input.name = prefix + "-" + newIndex + "-attachment";
        input.files = dt.files;
        rowDiv.appendChild(input);

        if (parentId) {
          var fkInput = document.createElement("input");
          fkInput.type = "hidden";
          fkInput.name = prefix + "-" + newIndex + "-testlist";
          fkInput.value = parentId;
          rowDiv.appendChild(fkInput);
        }

        formsetInputsContainer.appendChild(rowDiv);

        currentTotal++;
      });

      if (totalFormsInput) {
        totalFormsInput.value = currentTotal;
      }
      this.value = "";
      updateAttachmentCounts();
    });

    // Remove pending attachment
    document.addEventListener("click", function(e) {
      var removeBtn = e.target.closest(".btn-remove-pending");
      if (removeBtn) {
        e.preventDefault();
        var index = removeBtn.getAttribute("data-index");
        var card = document.getElementById("pending-attach-" + index);
        if (card) { card.remove(); }
        var row = document.getElementById("formset-row-" + index);
        if (row) { row.remove(); }
        updateAttachmentCounts();
      }
    });

    updateAttachmentCounts();
  }

  function initScopeSelect() {
    var select = document.getElementById("tl-machine-scope-select");
    var hintText = document.getElementById("tl-scope-info-text");
    if (!select || !hintText) { return; }

    select.addEventListener("change", function () {
      var val = this.value;
      if (val === "base") {
        hintText.textContent = "Changes apply to every assigned machine";
      } else {
        var opt = this.options[this.selectedIndex];
        var text = opt ? opt.textContent.trim() : "";
        hintText.textContent = "Viewing machine scope for " + text;
      }
    });
  }

  function renderLivePreview() {
    var container = document.getElementById("tl-preview-container");
    if (!container) { return; }

    var nameInput = document.getElementById("id_name");
    var nameVal = nameInput ? nameInput.value.trim() : "";
    if (!nameVal) { nameVal = "Untitled Test List"; }

    var slugInput = document.getElementById("id_slug");
    var slugVal = slugInput ? slugInput.value.trim() : "";

    var descInput = document.getElementById("id_description");
    var descVal = descInput ? descInput.value.trim() : "";

    var warnInput = document.getElementById("id_warning_message");
    var warnVal = warnInput ? warnInput.value.trim() : "";

    var jsInput = document.getElementById("id_javascript");
    var jsVal = jsInput ? jsInput.value.trim() : "";

    var html = '<div class="tl-preview-banner">' +
      '<i class="fa fa-eye" aria-hidden="true"></i> ' +
      '<span><strong>Preview Mode</strong> — This is a live demonstration of how this Test List appears when performed.</span>' +
      '</div>';

    html += '<div class="tl-preview-card">';
    html += '<h2 class="tl-preview-title">' + escapeHtml(nameVal) + (slugVal ? ' <span style="font-size:14px; font-weight:normal; color:#8a929e;">(' + escapeHtml(slugVal) + ')</span>' : '') + '</h2>';

    if (descVal) {
      html += '<div class="tl-preview-desc">' + descVal + '</div>';
    }

    if (warnVal) {
      html += '<div class="tl-preview-warning"><i class="fa fa-exclamation-triangle"></i> ' + escapeHtml(warnVal) + '</div>';
    }

    if (jsVal) {
      html += '<div style="margin-bottom:14px; font-size:12px; color:#6366f1; background:#eef2ff; border:1px solid #e0e7ff; padding:6px 10px; border-radius:3px;">' +
        '<i class="fa fa-code"></i> JavaScript logic active on perform page' +
        '</div>';
    }

    // Interleaved items in visual top-to-bottom order
    var rows = document.querySelectorAll("#tl-tests-tbody tr.tl-member-item");
    var inDirectTable = false;

    rows.forEach(function (r) {
      var del = r.querySelector("input[name$='-DELETE']");
      var isDel = del && (del.checked || del.value === "true");
      var isHidden = r.style.display === "none";
      if (isDel || isHidden) { return; }

      if (r.classList.contains("tl-test-row")) {
        if (!inDirectTable) {
          html += '<div style="margin-top:16px;">' +
            '<table class="tl-table tl-tests-table" style="border: 1px solid #e2e8f0; border-radius: 4px; overflow: hidden; margin-bottom: 16px;">' +
            '<thead><tr>' +
            '<th class="tl-th-test">TEST</th>' +
            '<th class="tl-th-category">CATEGORY</th>' +
            '<th class="tl-th-type">TYPE</th>' +
            '<th class="tl-th-ref">REFERENCE</th>' +
            '<th class="tl-th-tol">TOLERANCE</th>' +
            '<th style="width:140px; text-align:right;">INPUT</th>' +
            '</tr></thead><tbody>';
          inDirectTable = true;
        }

        var nameElem = r.querySelector(".tl-test-name");
        var name = nameElem ? nameElem.textContent.trim() : "";
        var catElem = r.querySelector(".tl-cat-pill");
        var cat = catElem ? catElem.textContent.trim() : "";
        var catClass = catElem ? catElem.className : "tl-cat-pill";
        var typeBadge = r.querySelector(".tl-type-badge");
        var typeBadgeText = typeBadge ? typeBadge.textContent.trim() : "";
        var typeBadgeClass = typeBadge ? typeBadge.className : "tl-type-badge";
        var typeLabel = r.querySelector(".tl-type-label");
        var typeLabelText = typeLabel ? typeLabel.textContent.trim() : "";
        var refElem = r.querySelector(".tl-cell-ref");
        var refText = refElem ? refElem.textContent.trim() : "—";
        var tolElem = r.querySelector(".tl-cell-tol");
        var tolText = tolElem ? tolElem.textContent.trim() : "—";

        html += '<tr>' +
          '<td class="tl-cell-test"><div class="tl-test-name">' + escapeHtml(name) + '</div></td>' +
          '<td class="tl-cell-category"><span class="' + escapeHtml(catClass) + '">' + escapeHtml(cat) + '</span></td>' +
          '<td class="tl-cell-type"><div class="tl-type-pill-wrap"><span class="' + escapeHtml(typeBadgeClass) + '">' + escapeHtml(typeBadgeText) + '</span> <span class="tl-type-label">' + escapeHtml(typeLabelText) + '</span></div></td>' +
          '<td class="tl-cell-ref"><span class="tl-val-text">' + escapeHtml(refText) + '</span></td>' +
          '<td class="tl-cell-tol"><span class="tl-val-text">' + escapeHtml(tolText) + '</span></td>' +
          '<td style="text-align:right;"><input type="text" placeholder="Value..." class="tl-preview-mock-input" disabled></td>' +
          '</tr>';
      } else if (r.classList.contains("tl-sublist-row")) {
        if (inDirectTable) {
          html += '</tbody></table></div>';
          inDirectTable = false;
        }

        var subNameElem = r.querySelector(".tl-sublist-name");
        var subName = subNameElem ? subNameElem.textContent.trim() : "Sublist";
        var subCountElem = r.querySelector(".tl-sublist-count");
        var subCount = subCountElem ? subCountElem.textContent.trim() : "0";

        html += '<div class="tl-preview-sublist-header"><i class="fa fa-folder-o text-warning"></i> <span>' + escapeHtml(subName) + '</span> <span class="tl-sublist-count">' + escapeHtml(subCount) + '</span></div>';

        var subRows = r.querySelectorAll("tbody tr.tl-sublist-test-row");
        html += '<table class="tl-table tl-sublist-table" style="border:1px solid #e2e8f0; border-top:0; margin-bottom:16px;">';
        html += '<thead><tr><th class="tl-th-test">TEST</th><th class="tl-th-category">CATEGORY</th><th class="tl-th-type">TYPE</th><th class="tl-th-ref">REFERENCE</th><th class="tl-th-tol">TOLERANCE</th><th style="width:140px; text-align:right;">INPUT</th></tr></thead><tbody>';

        subRows.forEach(function (sr) {
          var tname = sr.querySelector(".tl-test-name") ? sr.querySelector(".tl-test-name").textContent.trim() : "";
          var tcat = sr.querySelector(".tl-cat-pill") ? sr.querySelector(".tl-cat-pill").textContent.trim() : "";
          var tcatClass = sr.querySelector(".tl-cat-pill") ? sr.querySelector(".tl-cat-pill").className : "tl-cat-pill";
          var tb = sr.querySelector(".tl-type-badge") ? sr.querySelector(".tl-type-badge").textContent.trim() : "";
          var tbClass = sr.querySelector(".tl-type-badge") ? sr.querySelector(".tl-type-badge").className : "tl-type-badge";
          var tl = sr.querySelector(".tl-type-label") ? sr.querySelector(".tl-type-label").textContent.trim() : "";
          var tref = sr.querySelector(".tl-cell-ref") ? sr.querySelector(".tl-cell-ref").textContent.trim() : "—";
          var ttol = sr.querySelector(".tl-cell-tol") ? sr.querySelector(".tl-cell-tol").textContent.trim() : "—";

          html += '<tr>' +
            '<td class="tl-cell-test"><div class="tl-test-name">' + escapeHtml(tname) + '</div></td>' +
            '<td class="tl-cell-category"><span class="' + escapeHtml(tcatClass) + '">' + escapeHtml(tcat) + '</span></td>' +
            '<td class="tl-cell-type"><div class="tl-type-pill-wrap"><span class="' + escapeHtml(tbClass) + '">' + escapeHtml(tb) + '</span> <span class="tl-type-label">' + escapeHtml(tl) + '</span></div></td>' +
            '<td class="tl-cell-ref"><span class="tl-val-text">' + escapeHtml(tref) + '</span></td>' +
            '<td class="tl-cell-tol"><span class="tl-val-text">' + escapeHtml(ttol) + '</span></td>' +
            '<td style="text-align:right;"><input type="text" placeholder="Value..." class="tl-preview-mock-input" disabled></td>' +
            '</tr>';
        });

        html += '</tbody></table>';
      }
    });

    if (inDirectTable) {
      html += '</tbody></table></div>';
      inDirectTable = false;
    }

    html += '</div>'; // close tl-preview-card

    container.innerHTML = html;
  }

  function initViewTabs() {
    var editorBtn = document.getElementById("tl-view-editor-btn");
    var previewBtn = document.getElementById("tl-view-preview-btn");
    var previewContainer = document.getElementById("tl-preview-container");

    var editContainers = [
      document.getElementById("tl-details-card"),
      document.getElementById("tl-tests-card"),
      document.querySelector(".tl-bottom-actions"),
      document.getElementById("tl-attachments-card"),
      document.getElementById("tl-parents-card"),
      document.querySelector(".submit-row")
    ];

    if (!editorBtn || !previewBtn) { return; }

    function setView(view) {
      if (view === "preview") {
        editorBtn.classList.remove("active");
        previewBtn.classList.add("active");
        editContainers.forEach(function (el) {
          if (el) { el.style.display = "none"; }
        });
        if (previewContainer) {
          previewContainer.style.display = "block";
          renderLivePreview();
        }
      } else {
        previewBtn.classList.remove("active");
        editorBtn.classList.add("active");
        if (previewContainer) {
          previewContainer.style.display = "none";
        }
        editContainers.forEach(function (el) {
          if (el) { el.style.display = ""; }
        });
      }
    }

    editorBtn.addEventListener("click", function (e) {
      e.preventDefault();
      setView("editor");
    });

    previewBtn.addEventListener("click", function (e) {
      e.preventDefault();
      setView("preview");
    });
  }

  document.addEventListener("htmx:afterSwap", function () {
    initSortables();
    updateCounts();
  });
  document.addEventListener("htmx:load", function () {
    initSortables();
    updateCounts();
  });

  document.addEventListener("DOMContentLoaded", function () {
    initSortables();
    updateCounts();
    sortBuilderItemsByOrder();
    syncOrder();
    initSublistToggles();
    initAttachmentsSection();
    initScopeSelect();
    initViewTabs();
  });

  if (document.readyState === "complete" || document.readyState === "interactive") {
    setTimeout(function () {
      initSortables();
      updateCounts();
      sortBuilderItemsByOrder();
      syncOrder();
      initSublistToggles();
      initAttachmentsSection();
      initScopeSelect();
      initViewTabs();
    }, 20);
  }
})();
