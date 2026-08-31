/**
 * Test List Builder — Drag-and-drop reordering, HTMX interactions,
 * and Django formset synchronization for Tests & Sublists.
 */
(function () {
  "use strict";

  var activeSwapCard = null;

  function updateCounts() {
    var rows = document.querySelectorAll("#tl-tests-tbody tr.tl-test-row");
    var visibleCount = 0;
    rows.forEach(function (r) {
      var del = r.querySelector("input[name$='-DELETE']");
      var isDel = del && (del.checked || del.value === "true");
      var isHidden = r.style.display === "none";
      if (!isDel && !isHidden) {
        visibleCount++;
      }
    });
    var badge = document.getElementById("tl-tests-count");
    if (badge) { badge.textContent = visibleCount; }
    var emptyMsg = document.getElementById("tl-empty-tests-msg");
    if (emptyMsg) {
      emptyMsg.style.display = visibleCount === 0 ? "block" : "none";
    }
  }

  function syncOrder() {
    var order = 0;
    // Direct tests
    var rows = document.querySelectorAll("#tl-tests-tbody tr.tl-test-row");
    rows.forEach(function (r) {
      var del = r.querySelector("input[name$='-DELETE']");
      var isDel = del && (del.checked || del.value === "true");
      var isHidden = r.style.display === "none";
      var orderInput = r.querySelector(".tl-order-input");
      if (orderInput) {
        if (!isDel && !isHidden) {
          orderInput.value = order;
          order++;
        } else {
          orderInput.value = "";
        }
      }
    });

    // Sublists
    var cards = document.querySelectorAll("#tl-sublists-container .tl-sublist-card");
    cards.forEach(function (c) {
      var del = c.querySelector("input[name$='-DELETE']");
      var isDel = del && (del.checked || del.value === "true");
      var isHidden = c.style.display === "none";
      var orderInput = c.querySelector(".tl-sublist-order-input");
      if (orderInput) {
        if (!isDel && !isHidden) {
          orderInput.value = order;
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
          var temp = document.createElement("div");
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
        var container = document.getElementById("tl-sublists-container");
        if (!container) { return; }
        var temp = document.createElement("div");
        temp.innerHTML = html.trim();
        var newCard = temp.firstElementChild;
        if (newCard) {
          container.appendChild(newCard);
          if (totalFormsInput) { totalFormsInput.value = currentIndex + 1; }
          if (window.htmx) { htmx.process(newCard); }
          syncOrder();
          initSortables();
        }
      });
  }

  function initSortables() {
    var $ = window.django && window.django.jQuery ? window.django.jQuery : (window.jQuery || window.$);
    if ($ && $.fn && $.fn.sortable) {
      try {
        $("#tl-tests-tbody").sortable({
          handle: ".tl-drag-handle",
          items: "tr.tl-test-row",
          axis: "y",
          helper: function (e, tr) {
            var $originals = tr.children();
            var $helper = tr.clone();
            $helper.children().each(function (index) {
              $(this).width($originals.eq(index).width());
            });
            return $helper;
          },
          update: function () {
            syncOrder();
          }
        });

        $("#tl-sublists-container").sortable({
          handle: ".tl-sublist-header",
          items: ".tl-sublist-card",
          axis: "y",
          update: function () {
            syncOrder();
          }
        });
      } catch (err) {}
    }

    var tbody = document.getElementById("tl-tests-tbody");
    if (tbody) {
      tbody.querySelectorAll("tr.tl-test-row").forEach(function (row) {
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

  document.addEventListener("click", function (e) {
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
    syncOrder();
    initAttachmentsSection();
  });

  if (document.readyState === "complete" || document.readyState === "interactive") {
    setTimeout(function () {
      initSortables();
      updateCounts();
      syncOrder();
      initAttachmentsSection();
    }, 20);
  }
})();
