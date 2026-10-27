var tables = ["testlistcycles", "testlists", "tests"];
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
      val = JSON.stringify(selected);
    }
    $("input[name="+type+"]").attr("value", val);
}

for (var i=0; i < tables.length; i++){

    dataTables[tables[i]] = $("#"+ tables[i] + "-table").dataTable({
        buttons: [
            {extend: "selectAll", className: "button"},
            {extend: "selectNone", className: "button"},
            {
              text: gettext("Select Filtered"),
              className: "button",
              action: function () {
                $(this).DataTable().rows( {search:'applied'} ).select();
              }
            },
            {extend: "pageLength", className: "button"},
        ],
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

function tpkError(msg){
  alert(msg);
}


var converters = {
  'tests': function(o){
      return [
          o.fields.name,
          o.fields.category[0],
          window.test_types[o.fields.type],
          o.fields.description
      ];
  },
  'testlists': function(o){
      return [
          o.fields.name,
          o.fields.description
      ];
  },
  'testlistcycles': function(o){
      return [
          o.fields.name,
          o.fields.description
      ];
  }
};



function loadTestPack(tpk){

  var meta = tpk.meta;
  var version = parseVersion(meta.version);

  $("#version").text(meta.version);
  $("#name").text(meta.name);
  $("#created-by").text(meta.contact);
  $("#description").text(meta.description);
  var models = ["tests", "testlists", "testlistcycles"];
  var model_map = {'tests': 'qa.test' , 'testlists': 'qa.testlist' , 'testlistcycles': 'qa.testlistcycle'};
  var objects_to_imp = {'tests': [], 'test_lists': [], 'test_list_cycles': []};
  _.each(models, function(model){
        var objects = _.map(tpk.objects[model], function(o){return JSON.parse(o);});
        var objects_to_imp = [];
        var table = dataTables[model];
        var converter = converters[model];
        _.each(objects, function(model_objects){
            table.row.add([model_objects.key].concat(converter(model_objects['object'])));
        });
        table.draw();
        $("#"+model+"-table_wrapper .buttons-select-all").click();

  });

}

$("#id_testpack").on("change", function(e){
    var files = e.target.files;
    for (var i = 0, f; f = files[i]; i++) {

      var reader = new FileReader();

      reader.onload = (function(tpkFile) {
        return function(e) {
          var data;
          $("#id_testpack_data").val(e.target.result);
          try {
            data = JSON.parse(e.target.result);
          } catch(e){
            tpkError(gettext("This file isn't a valid test pack, so nothing was loaded. Choose a test pack file exported from QATrack+ and try again."));
            return;
          }
          loadTestPack(data);
        };
      })(f);

      reader.readAsText(f);
    }
});
