var tables = ["testlists", "testlistcycles", "tests"];
var dataTables = {};

// Strings come from Django's JavaScript catalogue (the template loads the
// admin jsi18n view). Fall back to English if it didn't load.
var gettext = window.gettext || function (s) { return s; };
var ngettext = window.ngettext || function (singular, plural, count) { return count === 1 ? singular : plural; };
var interpolate = window.interpolate || function (fmt, obj, named) {
    return named
        ? fmt.replace(/%\(\w+\)s/g, function (m) { return String(obj[m.slice(2, -2)]); })
        : fmt.replace(/%s/g, function () { return String(obj.shift()); });
};

// DataTables' own interface text (search box, paging, row counts)
var dataTablesLanguage = {
    search: gettext("Search:"),
    info: gettext("Showing _START_ to _END_ of _TOTAL_ entries"),
    infoEmpty: gettext("Showing 0 to 0 of 0 entries"),
    infoFiltered: gettext("(filtered from _MAX_ total entries)"),
    emptyTable: gettext("No data available in table"),
    zeroRecords: gettext("No matching records found"),
    paginate: {
        first: gettext("First"),
        previous: gettext("Previous"),
        next: gettext("Next"),
        last: gettext("Last")
    },
    select: {
        rows: {
            _: gettext("%d rows selected"),
            0: "",
            1: gettext("1 row selected")
        }
    },
    buttons: {
        selectAll: gettext("Select All"),
        selectNone: gettext("Select None"),
        pageLength: {
            _: gettext("Show %d Rows"),
            "-1": gettext("Show All Rows")
        }
    }
};

function selectedSummary(all, count){
    if (all){
        return gettext("All");
    }
    return interpolate(ngettext("%(count)s Selected", "%(count)s Selected", count), {count: count}, true);
}

function setSelected(type, selected){
    var all = selected.length > 0 && dataTables[type].column(0).data().length === selected.length
    $("#"+type + "-summary").text(selectedSummary(all, selected.length));
    var val;
    if (all){
      val = "all";
    } else {
      val = selected.join(",");
    }
    $("input[name="+type+"]").attr("value", val);
}

var columns = [];

for (var i=0; i < tables.length; i++){
    if (i === 0 || i === 1){
        columns = [{width: "40%", "targets": 0}];
    }else{
        columns = [{width: "20%", "targets": 1}, {width: "10%", "targets": 2}, {width: "10%", "targets": 3}];
    }

    dataTables[tables[i]] = $("#"+ tables[i] + "-table").dataTable({
        buttons: [
            {extend: "selectAll", className: "button"},
            {extend: "selectNone", className: "button"},
            {
              text: gettext("Select Filtered"),
              className: "button",
              action: function () {
                this.rows( {search:'applied'} ).select();
              }
            }
        ],
        columnDefs: columns,
        autoWidth: false,
        dom: 'Bfrtip',
        language: dataTablesLanguage,
          pagingType: "full_numbers",
          select: "multi",
          initComplete: function(settings, json){
              $(this).parents(".tp-container").find(".loading").remove();
              $(".dt-button").removeClass("dt-button");
          }
      }).show().DataTable().on('select deselect', function ( e, dt, type, indexes ) {
          if (type === 'row') {
            var data = dt.rows({selected: true}).data().pluck(0).toArray();
            var type = $(dt.table().container()).attr("id").split("-")[0];
            setSelected(type, data);
          }
      }).column(0).visible(false);
}


