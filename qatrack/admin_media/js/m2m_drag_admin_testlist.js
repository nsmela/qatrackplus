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

    var cloneBtn = e.target.closest(".tl-clone-test-btn");
    if (cloneBtn) {
      e.preventDefault();
      var cRow = cloneBtn.closest("tr.tl-test-row");
      var cTestId = cloneBtn.getAttribute("data-test-id") || (cRow && cRow.getAttribute("data-test-id"));
      if (!cTestId && cRow) {
        var tInput = cRow.querySelector("input[name$='-test']");
        if (tInput) { cTestId = tInput.value; }
      }
      if (cTestId) {
        addTestRow(cTestId);
      }
      return;
    }

    if (e.target.matches("[data-search-close]") || e.target.closest("[data-search-close]")) {
      var sModalClose = document.getElementById("tl-search-modal");
      if (sModalClose) { sModalClose.hidden = true; }
    }
    if (e.target.matches("[data-modal-close]") || e.target.closest("[data-modal-close]")) {
      var dModalClose = document.getElementById("tl-desc-modal-backdrop") || e.target.closest(".tl-modal-backdrop");
      if (dModalClose) { dModalClose.remove(); }
    }
    if (e.target.classList && e.target.classList.contains("tl-modal-backdrop")) {
      e.target.hidden = true;
      if (e.target.id === "tl-desc-modal-backdrop") { e.target.remove(); }
    }
  });

  document.addEventListener("submit", function (e) {
    if (e.target.matches("form")) {
      syncOrder();
    }
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      var sModalEsc = document.getElementById("tl-search-modal");
      if (sModalEsc && !sModalEsc.hidden) { sModalEsc.hidden = true; }
      var dModalEsc = document.getElementById("tl-desc-modal-backdrop");
      if (dModalEsc) { dModalEsc.remove(); }
    }
  });

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
  });

  if (document.readyState === "complete" || document.readyState === "interactive") {
    setTimeout(function () {
      initSortables();
      updateCounts();
      syncOrder();
    }, 20);
  }
})();
