require(['jquery', 'moment', 'autosize', 'select2', 'sl_utils'], function ($, moment, autosize) {

    $(document).ready(function () {

        var $priority = $('#id_issue_priority'),
            $tags = $('#id_issue_tags'),
            $pic_click = $('.pic_click'),
            $comments = $('#comments > dd > p');

        $comments.addClass('padding-left-10 white-space-pre');

        autosize($('textarea.autosize'));

        $tags.select2({
            minimumResultsForSearch: 10,
            width: '100%',
            templateResult: function(res) {
                if (res.id) {
                    return $('<div class="select2-result-repository clearfix" title="' + tags[res.id][1] + '"><span class="pull-left">' + res.text + '</span><span class="pull-right no-wrap">' + tags[res.id][1] + '</span></div>');
                } else {
                    return res.text;
                }
            }
        });

        $pic_click.click(function() {
            $('.pic_display').slideToggle('fast');
        });


        function generate_status_label(priority) {
            if (priority.id) {
                var colour = colours[priority.id];
                var $label = $('<span class="label" style="background-color: ' + colour + '">' + priority.text + '</span>');
                $label.css('background-color', colour);
                $label.css('border-color', colour);
                if (isTooBright(rgbaStringToArray(colour))) {
                    $label.css('color', 'black').children().css('color', 'black');
                }
                return $label;
            }
            return priority.text;
        }
        $priority.select2({
            templateResult: generate_status_label,
            templateSelection: generate_status_label,
            minimumResultsForSearch: 10,
            width: '100%'
        });

        var $status = $('#id_issue_status');
        function generate_issue_status_label(status) {
            if (status.id) {
                var colour = status_colours[status.id];
                var $label = $('<span class="label smooth-border" style="border-color: ' + colour + '; color: inherit; background-color: transparent;">' + status.text + '</span>');
                return $label;
            }
            return status.text;
        }
        if ($status.length) {
            $status.select2({
                templateResult: generate_issue_status_label,
                templateSelection: generate_issue_status_label,
                minimumResultsForSearch: 10,
                width: '100%'
            });
        }

        var $qa_logs = $('#id_qa_logs');
        function generate_qa_result(res) {
            if (res.loading) { return res.text; }
            var $div = $('<div class="select2-result-repository clearfix"><span>' + res.text + ' (' + res.date + ') - ' + res.unit + '</span></div>');
            return $div;
        }
        function generate_qa_selection(res, container) {
            var $label = $('<span>' + res.text + '</span>');
            return $label;
        }
        function process_qa_results(data, params) {
            var results = [];
            for (var i in data.qa_logs) {
                var f_id = data.qa_logs[i][0],
                    f_title = data.qa_logs[i][1],
                    f_date = data.qa_logs[i][2] !== "In Progress" ? moment(data.qa_logs[i][2]).format(siteConfig.MOMENT_DATETIME_FMT) : "In Progress",
                    f_unit = data.qa_logs[i][3];
                results.push({id: f_id, text: f_title, date: f_date, unit: f_unit});
            }
            params.page = params.page || 1;
            return {
                results: results,
                pagination: {
                    more: (params.page * 30) < data.total_count
                }
            };
        }
        if ($qa_logs.length) {
            $qa_logs.select2({
                ajax: {
                    url: QAURLs.QA_SEARCHER,
                    dataType: 'json',
                    delay: '500',
                    data: function (params) {
                        return {
                            q: params.term, // search term
                            page: params.page
                        };
                    },
                    processResults: process_qa_results,
                    cache: true
                },
                escapeMarkup: function (markup) { return markup; },
                minimumInputLength: 1,
                templateResult: generate_qa_result,
                templateSelection: generate_qa_selection,
                width: '100%'
            });
        }

        var $related_se = $('#id_service_events');
        function generate_related_result(res) {
            if (res.loading) { return res.text; }
            var colour = status_colours_dict[se_statuses[res.id]];
            var $div = $('<div class="select2-result-repository clearfix"><span>' + res.text + '  (' + res.date + ') </span><span class="label smooth-border pull-right" style="border-color: ' + colour + ';">' + res.status + '</span></div>');
            return $div;
        }
        function generate_related_selection(res, container) {
            var colour = status_colours_dict[se_statuses[res.id]];
            $(container).css('background-color', colour);
            $(container).css('border-color', colour);
            if (isTooBright(rgbaStringToArray(colour))) {
                $(container).css('color', 'black').children().css('color', 'black');
            }
            var $label = $('<span>' + res.text + '</span>');
            return $label;
        }
        function process_related_results(data, params) {
            var results = [];
            for (var i in data.service_events) {
                var se_id = data.service_events[i][0],
                    se_status_id = data.service_events[i][1],
                    se_problem_description = data.service_events[i][2],
                    se_date = moment(data.service_events[i][3]).format(siteConfig.MOMENT_DATETIME_FMT),
                    se_status_name = data.service_events[i][4];
                results.push({id: se_id, text: se_id, title: se_problem_description, date: se_date, status: se_status_name});
                se_statuses[se_id] = se_status_id;
            }
            params.page = params.page || 1;
            return {
                results: results,
                pagination: {
                    more: (params.page * 30) < data.total_count
                }
            };
        }
        if ($related_se.length) {
            $related_se.select2({
                ajax: {
                    url: QAURLs.SE_SEARCHER,
                    dataType: 'json',
                    delay: '500',
                    data: function (params) {
                        return {
                            q: params.term, // search term
                            page: params.page
                        };
                    },
                    processResults: process_related_results,
                    cache: true
                },
                escapeMarkup: function (markup) { return markup; },
                minimumInputLength: 1,
                templateResult: generate_related_result,
                templateSelection: generate_related_selection,
                width: '100%'
            });
        }

        var $fault_logs = $('#id_fault_logs');
        function generate_fault_result(res) {
            if (res.loading) { return res.text; }
            var $div = $('<div class="select2-result-repository clearfix"><span>' + res.text + ' (' + res.date + ') - ' + res.unit + '</span></div>');
            return $div;
        }
        function generate_fault_selection(res, container) {
            var $label = $('<span>' + res.text + '</span>');
            return $label;
        }
        function process_fault_results(data, params) {
            var results = [];
            for (var i in data.faults) {
                var f_id = data.faults[i][0],
                    f_title = data.faults[i][1],
                    f_date = moment(data.faults[i][2]).format(siteConfig.MOMENT_DATETIME_FMT),
                    f_unit = data.faults[i][3];
                results.push({id: f_id, text: "Fault Log " + f_id + ": " + f_title, date: f_date, unit: f_unit});
            }
            params.page = params.page || 1;
            return {
                results: results,
                pagination: {
                    more: (params.page * 30) < data.total_count
                }
            };
        }
        if ($fault_logs.length) {
            $fault_logs.select2({
                ajax: {
                    url: QAURLs.FAULT_SEARCHER,
                    dataType: 'json',
                    delay: '500',
                    data: function (params) {
                        return {
                            q: params.term, // search term
                            page: params.page
                        };
                    },
                    processResults: process_fault_results,
                    cache: true
                },
                escapeMarkup: function (markup) { return markup; },
                minimumInputLength: 1,
                templateResult: generate_fault_result,
                templateSelection: generate_fault_selection,
                width: '100%'
            });
        }

    });




});
