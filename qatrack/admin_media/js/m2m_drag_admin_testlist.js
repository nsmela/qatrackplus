/**
 * Test List Builder — Modernized drag-and-drop reordering, HTMX interactions,
 * and Django formset synchronization for Tests & Sublists.
 */
(function ($) {
  "use strict";

  var activeSwapCard = null;

  function updateCounts() {
    var visibleTests = $("#tl-tests-tbody tr.tl-test-row").filter(function () {
      return !$(this).find("input[name$='-DELETE']").is(":checked") && $(this).is(":visible");
    });
    var count = visibleTests.length;
    $("#tl-tests-count").text(count);
    if (count === 0) {
      $("#tl-empty-tests-msg").show();
    } else {
      $("#tl-empty-tests-msg").hide();
    }
  }

  function syncOrder() {
    var order = 0;
    // Direct tests
    $("#tl-tests-tbody tr.tl-test-row").each(function () {
      var isDeleted = $(this).find("input[name$='-DELETE']").is(":checked");
      if (!isDeleted && $(this).is(":visible")) {
        $(this).find(".tl-order-input").val(order);
        order++;
      } else {
        $(this).find(".tl-order-input").val("");
      }
    });

    // Sublists
    $("#tl-sublists-container .tl-sublist-card").each(function () {
      var isDeleted = $(this).find("input[name$='-DELETE']").is(":checked");
      if (!isDeleted && $(this).is(":visible")) {
        $(this).find(".tl-sublist-order-input").val(order);
        order++;
      } else {
        $(this).find(".tl-sublist-order-input").val("");
      }
    });

    updateCounts();
  }

  function initSortables() {
    if ($.fn.sortable) {
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
    }
  }

  function openSearchModal(mode, swapCard) {
    activeSwapCard = swapCard || null;
    var modal = document.getElementById("tl-search-modal");
    if (!modal) { return; }

    var title = document.getElementById("tl-search-title-text");
    var input = document.getElementById("tl-search-input");
    var resultsBox = document.getElementById("tl-search-results-box");

    var originalId = $("#tl-tests-card").data("original-id") || "";

    if (mode === "test") {
      title.textContent = "Select Test to Add";
      input.placeholder = "Search by test name, macro slug or category…";
      input.setAttribute("hx-get", "/admin/qa/testlist/search-tests/");
      input.value = "";
    } else {
      title.textContent = activeSwapCard ? "Change Sublist" : "Select Sublist to Add";
      input.placeholder = "Search available test lists…";
      var url = "/admin/qa/testlist/search-sublists/" + (originalId ? "?current_id=" + encodeURIComponent(originalId) : "");
      input.setAttribute("hx-get", url);
      input.value = "";
    }

    modal.hidden = false;
    if (window.htmx) {
      htmx.process(input);
      // Trigger initial search to show default results
      htmx.ajax("GET", input.getAttribute("hx-get"), { target: resultsBox, swap: "innerHTML" });
    }
    setTimeout(function () { input.focus(); }, 50);
  }

  function addTestRow(testId) {
    var totalFormsInput = $("#id_testlistmembership_set-TOTAL_FORMS");
    var currentIndex = parseInt(totalFormsInput.val(), 10) || 0;
    var originalId = $("#tl-tests-card").data("original-id") || "";

    var url = "/admin/qa/testlist/add-test-row/?test_id=" + encodeURIComponent(testId) +
              "&index=" + currentIndex +
              "&test_list_id=" + encodeURIComponent(originalId);

    $.get(url, function (html) {
      var $newRow = $(html);
      $("#tl-tests-tbody").append($newRow);
      totalFormsInput.val(currentIndex + 1);
      if (window.htmx) { htmx.process($newRow[0]); }
      syncOrder();
      initSortables();
    });
  }

  function addSublistCard(childId) {
    if (activeSwapCard) {
      // Swap existing sublist
      var card = $(activeSwapCard);
      var index = card.data("index");
      var originalId = $("#tl-tests-card").data("original-id") || "";
      var url = "/admin/qa/testlist/add-sublist-card/?child_id=" + encodeURIComponent(childId) +
                "&index=" + index +
                "&parent_id=" + encodeURIComponent(originalId);
      $.get(url, function (html) {
        var $newCard = $(html);
        card.replaceWith($newCard);
        if (window.htmx) { htmx.process($newCard[0]); }
        activeSwapCard = null;
        syncOrder();
        initSortables();
      });
      return;
    }

    var totalFormsInput = $("#id_children-TOTAL_FORMS");
    var currentIndex = parseInt(totalFormsInput.val(), 10) || 0;
    var originalId = $("#tl-tests-card").data("original-id") || "";

    var url = "/admin/qa/testlist/add-sublist-card/?child_id=" + encodeURIComponent(childId) +
              "&index=" + currentIndex +
              "&parent_id=" + encodeURIComponent(originalId);

    $.get(url, function (html) {
      var $newCard = $(html);
      $("#tl-sublists-container").append($newCard);
      totalFormsInput.val(currentIndex + 1);
      if (window.htmx) { htmx.process($newCard[0]); }
      syncOrder();
      initSortables();
    });
  }

  $(document).ready(function () {
    initSortables();
    updateCounts();
    syncOrder();

    // Add Test buttons
    $(document).on("click", "#tl-header-add-test-btn, #tl-add-test-btn", function (e) {
      e.preventDefault();
      openSearchModal("test");
    });

    // Add Sublist button
    $(document).on("click", "#tl-add-sublist-btn", function (e) {
      e.preventDefault();
      openSearchModal("sublist");
    });

    // Change Sublist button
    $(document).on("click", ".tl-btn-change-sublist", function (e) {
      e.preventDefault();
      var card = $(this).closest(".tl-sublist-card");
      openSearchModal("sublist", card);
    });

    // Select Test from modal
    $(document).on("click", ".tl-btn-select-test, .tl-search-test-item", function (e) {
      e.preventDefault();
      var testId = $(this).data("test-id") || $(this).closest(".tl-search-test-item").data("test-id");
      if (testId) {
        addTestRow(testId);
        var modal = document.getElementById("tl-search-modal");
        if (modal) { modal.hidden = true; }
      }
    });

    // Select Sublist from modal
    $(document).on("click", ".tl-btn-select-sublist, .tl-search-sublist-item", function (e) {
      e.preventDefault();
      var childId = $(this).data("child-id") || $(this).closest(".tl-search-sublist-item").data("child-id");
      if (childId) {
        addSublistCard(childId);
        var modal = document.getElementById("tl-search-modal");
        if (modal) { modal.hidden = true; }
      }
    });

    // Remove Test
    $(document).on("click", ".tl-delete-test-btn", function (e) {
      e.preventDefault();
      var $row = $(this).closest("tr.tl-test-row");
      var deleteCheckbox = $row.find("input[name$='-DELETE']");
      if (deleteCheckbox.length) {
        deleteCheckbox.prop("checked", true);
      }
      $row.fadeOut(150, function () {
        syncOrder();
      });
    });

    // Remove Sublist
    $(document).on("click", ".tl-btn-remove-sublist", function (e) {
      e.preventDefault();
      var $card = $(this).closest(".tl-sublist-card");
      var deleteCheckbox = $card.find("input[name$='-DELETE']");
      if (deleteCheckbox.length) {
        deleteCheckbox.prop("checked", true);
      }
      $card.fadeOut(150, function () {
        syncOrder();
      });
    });

    // Duplicate / Clone Test
    $(document).on("click", ".tl-clone-test-btn", function (e) {
      e.preventDefault();
      var testId = $(this).data("test-id");
      if (testId) {
        addTestRow(testId);
      }
    });

    // Form submit: ensure orders are consecutively indexed
    $("form").on("submit", function () {
      syncOrder();
    });

    // HTMX afterSwap re-init
    document.body.addEventListener("htmx:afterSwap", function (evt) {
      initSortables();
      updateCounts();
    });
  });
})(django.jQuery || window.jQuery || $);
