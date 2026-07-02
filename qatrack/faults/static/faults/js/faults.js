require(['jquery', 'lodash', 'moment', 'flatpickr', 'select2', 'comments', 'sl_utils'], function($, lodash, moment) {
    "use strict";
    $(document).ready(function () {

        var unitInfo;
        var s2config = {
            width: "100%",
            dropdownParent: null
        };
        var $faultModalToggle = $(".fault-modal-toggle");
        var $faultModal = $("#fault-modal");
        var $saveFault = $("#save_fault");

        if ($faultModal.length > 0){
            s2config.dropdownParent = $faultModal;
        }
        var $faultForm = $faultModal.find("form");
        var $faultMessage = $("#modal-fault-message");

        function resetModalFaultForm(){
            $faultMessage.html("");
            $faultModal.find(".has-error").removeClass("has-error");
            $faultModal.find(".has-success").removeClass("has-success");
            $faultModal.find(".error-message").remove();
        }

        $.ajax({
            type: "GET",
            url: QAURLs.UNIT_INFO,
            data: {'serviceable_only': true},
            success: function(data){
                unitInfo = data;
                configureFaults();
            },
            error: function(data){
                alert(QATranslations.ERROR_INITIALIZATION);
            }
        });

        function configureFaults(){

            var $date_time = $("#id_fault-occurred");
            if ($date_time.length) {
                var dt_val = $date_time.val();
                var init_date = dt_val ? moment(dt_val, [siteConfig.MOMENT_DATETIME_FMT, "YYYY-MM-DD HH:mm"]).format(siteConfig.MOMENT_DATETIME_FMT) : null;
                if (!init_date) {
                    init_date = moment().format(siteConfig.MOMENT_DATETIME_FMT);
                }
                
                // Clear the raw ISO string from the input so Flatpickr doesn't try to parse it natively
                $date_time.val("");
                
                $date_time.flatpickr({
                    enableTime: true,
                    time_24hr: true,
                    minuteIncrement: 1,
                    dateFormat: siteConfig.FLATPICKR_DATETIME_FMT,
                    defaultDate: init_date,
                    allowInput: true,
                    parseDate: function(datestr, format) {
                        return moment(datestr, [siteConfig.MOMENT_DATETIME_FMT, "YYYY-MM-DD HH:mm"]).toDate();
                    },
                    formatDate: function(date, format) {
                        return moment(date).format(siteConfig.MOMENT_DATETIME_FMT);
                    },
                    onOpen: [
                        function(selectedDates, dateStr, instance) {
                            if (dateStr === '') {
                                instance.setDate(new Date());
                            }
                        }
                    ]
                });
            }
            var $modality = $("#id_fault-modality").select2(s2config);
            var $related_se = $('#id_fault-related_service_events');
            var initialLoad = true;
            var $unit = $("#id_fault-unit");

            var faultTypeCache = {};

            // Ensure description container exists
            var $faultTypeDescContainer = $('#inline-fault-type-descriptions');
            if ($faultTypeDescContainer.length === 0) {
                $faultTypeDescContainer = $('<div id="inline-fault-type-descriptions" class="margin-top-10"></div>');
                $("#id_fault-fault_types_field").parent().append($faultTypeDescContainer);
            } else {
                $faultTypeDescContainer.empty();
            }

            function addFaultDescriptions(selectedData) {
                var selected = $.extend(true, [], selectedData);
                selected.sort(function(a, b) { return ((a.code || a.text) || "").localeCompare((b.code || b.text) || ""); });
                var newCodes = $.map(selected, function(el) { return (el.code || el.text || "").toString(); });

                $faultTypeDescContainer.find(".fault-type-desc-block").each(function(idx, el) {
                    var $el = $(el);
                    var rawCode = $el.data("code");
                    var code = rawCode !== undefined ? rawCode.toString() : "";
                    var loc = newCodes.indexOf(code);
                    if (loc < 0) {
                        $el.remove();
                    } else {
                        newCodes.splice(loc, 1);
                        selected.splice(loc, 1);
                    }
                });

                $.each(selected, function(idx, el) {
                    var code = el.code || el.text;
                    var fId = el.id;
                    
                    if (faultTypeCache[fId]) {
                        if (el.description === undefined) el.description = faultTypeCache[fId].description;
                        if (el.slug === undefined) el.slug = faultTypeCache[fId].slug;
                    } else if (el.description !== undefined || el.slug !== undefined) {
                        faultTypeCache[fId] = {
                            description: el.description,
                            slug: el.slug
                        };
                    }

                    var desc = el.description || "<em>" + QATranslations.NO_DESCRIPTION_AVAILABLE + "</em>";
                    var slug = el.slug || "";
                    var linkUrl = QAURLs.FAULT_TYPE_DETAILS ? QAURLs.FAULT_TYPE_DETAILS.replace('__SLUG__', slug) : "";
                    
                    var html = '<div class="fault-card-hover fault-type-desc-block margin-bottom-10" data-code="' + code + '" data-slug="' + slug + '" data-id="' + fId + '" style="display: flex; align-items: flex-start; border-left: 4px solid #3c8dbc; padding: 8px 12px; border-radius: 0 3px 3px 0; box-shadow: 0 1px 1px rgba(0,0,0,0.05);">';
                    
                    html += '  <div style="flex-shrink: 0; margin-right: 15px; display: flex; gap: 10px; align-items: center; margin-top: 2px;">';
                    html += '    <i class="fa fa-trash fa-lg text-danger remove-fault-type" style="cursor: pointer;" title="' + QATranslations.REMOVE + '"></i>';
                    if (window.can_edit_fault_type && slug) {
                        html += '    <i class="fa fa-pencil fa-lg text-primary edit-fault-type-desc" style="cursor: pointer;" title="' + QATranslations.EDIT_DESCRIPTION + '"></i>';
                    }
                    if (slug) {
                        html += '    <a href="' + linkUrl + '" target="_blank" class="text-info"><i class="fa fa-eye fa-lg"></i></a>';
                    }
                    html += '  </div>';
                    
                    html += '  <div style="flex-grow: 1; min-width: 0;">';
                    html += '    <strong style="display: block;">' + QATranslations.CODE + ': ' + code + '</strong>';
                    
                    html += '    <div class="margin-top-5 text-muted fault-type-desc-text"><span class="desc-content">' + desc + '</span></div>';

                    if (window.can_edit_fault_type && slug) {
                        var plainDesc = el.description || "";
                        html += '    <div class="margin-top-5 fault-type-desc-edit-form" style="display: none;">';
                        html += '      <textarea class="form-control input-sm desc-textarea" style="resize: vertical; margin-bottom: 5px;">' + plainDesc + '</textarea>';
                        html += '      <button type="button" class="btn btn-primary btn-xs save-fault-type-desc">' + QATranslations.SAVE + '</button>';
                        html += '      <button type="button" class="btn btn-default btn-xs cancel-fault-type-desc margin-left-5">' + QATranslations.CANCEL + '</button>';
                        html += '      <i class="fa fa-spinner fa-spin text-muted desc-save-spinner margin-left-5" style="display: none;"></i>';
                        html += '    </div>';
                    }
                    
                    html += '  </div>';
                    
                    html += '</div>';
                    
                    $faultTypeDescContainer.append(html);
                });
            }

            $faultTypeDescContainer.on('click', '.remove-fault-type', function() {
                var $card = $(this).closest('.fault-type-desc-block');
                var idToRemove = $card.data('id');
                if (idToRemove) {
                    var $ft = $("#id_fault-fault_types_field");
                    var currentVals = $ft.val() || [];
                    var newVals = $.grep(currentVals, function(val) {
                        return val != idToRemove;
                    });
                    $ft.val(newVals).trigger('change');
                }
            });
            
            $faultTypeDescContainer.on('click', '.edit-fault-type-desc', function() {
                var $card = $(this).closest('.fault-type-desc-block');
                $card.find('.fault-type-desc-text').hide();
                $card.find('.fault-type-desc-edit-form').show();
                $(this).hide();
            });
            
            $faultTypeDescContainer.on('click', '.cancel-fault-type-desc', function() {
                var $card = $(this).closest('.fault-type-desc-block');
                $card.find('.fault-type-desc-edit-form').hide();
                $card.find('.fault-type-desc-text').show();
                $card.find('.edit-fault-type-desc').show();
            });
            
            $faultTypeDescContainer.on('click', '.save-fault-type-desc', function() {
                var $card = $(this).closest('.fault-type-desc-block');
                var slug = $card.data('slug');
                var fId = $card.data('id');
                var newDesc = $card.find('.desc-textarea').val();
                
                var $saveBtn = $(this);
                var $cancelBtn = $card.find('.cancel-fault-type-desc');
                var $spinner = $card.find('.desc-save-spinner');
                
                $saveBtn.prop('disabled', true);
                $cancelBtn.prop('disabled', true);
                $spinner.show();
                
                var ajaxUrl = QAURLs.FAULT_TYPE_DESC_UPDATE.replace('__SLUG__', slug);
                
                $.ajax({
                    url: ajaxUrl,
                    type: 'POST',
                    data: {
                        description: newDesc,
                        csrfmiddlewaretoken: $('input[name=csrfmiddlewaretoken]').val()
                    },
                    success: function(response) {
                        if (response.status === 'success') {
                            var descText = response.description || "<em>" + QATranslations.NO_DESCRIPTION_AVAILABLE + "</em>";
                            $card.find('.desc-content').html(descText);
                            $card.find('.desc-textarea').val(response.description);
                            
                            if (faultTypeCache[fId]) {
                                faultTypeCache[fId].description = response.description;
                            }
                            
                            $card.find('.fault-type-desc-edit-form').hide();
                            $card.find('.fault-type-desc-text').show();
                            $card.find('.edit-fault-type-desc').show();
                        }
                    },
                    error: function() {
                        alert(QATranslations.FAILED_TO_UPDATE_DESC);
                    },
                    complete: function() {
                        $saveBtn.prop('disabled', false);
                        $cancelBtn.prop('disabled', false);
                        $spinner.hide();
                    }
                });
            });

            var $faultType = $("#id_fault-fault_types_field").select2({
                width: '100%',
                multiple: true,
                dropdownParent: s2config.dropdownParent,
                ajax: {
                    url: QAURLs.FAULT_TYPE_AUTOCOMPLETE,
                    dataType: 'json',
                    data: function(params){
                        return {
                            q: params.term,
                            unit: $unit.val(),
                            suggestions: 1
                        };
                    }
                },
                placeholder: '-----------',
                minimumInputLength: 2,
                selectOnClose: true,
                templateSelection: function(data, container) {
                    if (!data.id) return data.text;
                    $(container).css('display', 'none');
                    return '';
                }
            }).on("change", function(evt){
                addFaultDescriptions($faultType.select2('data'));
            });

            var alreadySelected = $faultType.val();
            if (alreadySelected){
                var completed = [];
                $.each(alreadySelected, function(idx, val){
                    $.ajax({
                        type: 'GET',
                        url: QAURLs.FAULT_TYPE_AUTOCOMPLETE,
                        dataType: 'json',
                        data: {
                            q: val,
                            unit: $unit.val(),
                            suggestions: 1
                        }
                    }).then(function(data){
                        var opt = data.results[0];
                        completed.push(opt);
                        if (completed.length === alreadySelected.length){
                            addFaultDescriptions(completed);
                        }
                    });
                });
            }



            $unit.select2(s2config).on("change", function(){
                var cur_unit = parseInt($unit.val(), 10);
                var unit_modalities = [];
                if (cur_unit in unitInfo){
                    unit_modalities = unitInfo[cur_unit].modalities;
                }
                var current_mod = parseInt($modality.val(), 10);
                var is_current_valid = isNaN(current_mod);
                for (var j=0; j<unit_modalities.length; j++) {
                    if (unit_modalities[j] == current_mod) { is_current_valid = true; break; }
                }
                if (!is_current_valid) {
                    $modality.val("").trigger("change");
                }

                $modality.find("option").each(function(i, opt){
                    var $opt = $(opt);
                    var mod_id = parseInt($(opt).val(), 10);
                    var enable = isNaN(mod_id);
                    for (var k=0; k<unit_modalities.length; k++) {
                        if (unit_modalities[k] == mod_id) { enable = true; break; }
                    }
                    $opt.prop('disabled', !enable);
                });
                // Refresh select2 without destroying to prevent visual clearing
                $modality.trigger("change.select2");

                if (cur_unit){
                    $modality.closest('.form-group').show();
                    $related_se.closest('.form-group').show();
                    $related_se.prop('disabled', false);
                    if (!initialLoad){
                        $related_se.find('option').remove();
                    }
                }else{
                    $modality.closest('.form-group').hide();
                    $related_se.closest('.form-group').hide();
                    $related_se.prop('disabled', true).find('option').remove();
                }

                initialLoad = false;

            });
            $unit.change();


            /* fault log modal operation */
            function faultSuccess(result){
                $faultMessage.append(
                    '<div class="help-block success-message"><i class="fa fa-check-circle-o"></i> '+
                    result.message +
                    '</div>'
                ).parent().addClass("has-success");
                setTimeout(function(){$faultModal.modal('hide');}, 2000);
            }
            function faultError(result){
                $.each(result.non_field_errors, function(k, v){
                    $faultMessage.append(
                        '<div class="help-block error-message"><i class="fa fa-ban"></i> '+
                        v +
                        '</div>'
                    ).parent().addClass("has-error");
                });
                $.each(result.errors, function(field, errs) {
                    var $field = $('#id_fault-' + field);
                    var $form_group = $field.parents('.form-group');

                    $form_group.addClass('has-error');

                    $.each(errs, function(err_idx, err) {
                        var $error_div = $('<div class="col-sm-12 help-block text-center error-message">' + err + '</div>');
                        $field.after($error_div);
                    });
                });
                $.each(result.review_errors, function(field, errs) {
                    if (Object.keys(errs).length === 0){
                        return;
                    }
                    var $field = $('#id_review-form-' + field + '-reviewed_by');
                    var $form_group = $field.parents('.form-group');

                    $form_group.addClass('has-error');

                    $.each(errs, function(err_idx, err) {
                        var $error_div = $('<p class="help-block text-center error-message">' + err + '</p>');
                        $field.parent().append($error_div);
                    });
                });
            }
            $saveFault.click(function(){
                resetModalFaultForm();
                $.ajax({
                    type: "POST",
                    url: $faultForm.data("create-url"),
                    data: $faultForm.serialize(),
                    success: function(data){
                        if (data.error){
                            faultError(data);
                        }else{
                            faultSuccess(data);
                        }
                    },
                    error: function(data){
                        faultError({'non_field_errors': ["Sorry, there was a server error."]});
                    }
                });
            });

            // Service Events Related ------------------------------------------------------------------------------
            function getRgbaArray(colour) {
                if (!colour) return [0,0,0,1];
                if (colour.indexOf('#') === 0) {
                    var hex = colour.replace('#', '');
                    if (hex.length === 3) hex = hex[0]+hex[0]+hex[1]+hex[1]+hex[2]+hex[2];
                    if (hex.length === 6) {
                        return [parseInt(hex.substr(0,2), 16), parseInt(hex.substr(2,2), 16), parseInt(hex.substr(4,2), 16), 1];
                    }
                }
                if (window.rgbaStringToArray) {
                    try { return window.rgbaStringToArray(colour); } catch(e) {}
                }
                var match = colour.match(/^rgb[a]?\((\d+),\s*(\d+),\s*(\d+)/);
                if (match) return [parseInt(match[1]), parseInt(match[2]), parseInt(match[3]), 1];
                return [0,0,0,1];
            }

            function generate_related_result(res) {
                if (res.loading) { return res.text; }
                if (res.is_new_link) {
                    return $('<div style="padding: 5px 0; color: #3c8dbc; font-weight: bold;"><i class="fa fa-plus"></i> ' + res.text + '</div>');
                }
                var description = res.title ? res.title.slice(0, 100) : "";
                if (res.title && res.title.length > 100){
                    description += "...";
                }

                var colour = status_colours_dict ? status_colours_dict[se_statuses[res.id]] : null;
                if (!colour) colour = '#ccc';
                
                var txtColor = 'white';
                if (colour && window.isTooBright && window.isTooBright(getRgbaArray(colour))) {
                    txtColor = 'black';
                }

                var sel = '<div class="select2-result-repository clearfix" style="padding-bottom: 5px;">';
                sel += '<div class="clearfix" style="margin-bottom: 3px;">';
                sel += '<strong>' + QATranslations.ID + ': ' + res.id + '</strong> <span style="opacity: 0.75;">(' + (res.date || "") + ')</span>';
                sel += '<span class="label pull-right" style="background-color: ' + colour + '; color: ' + txtColor + ';">' + (res.status || "") + '</span>';
                sel += '</div>';
                sel += '<div style="font-size: 12px; opacity: 0.8;">' + description + '</div>';
                sel += '</div>';
                return $(sel);
            }
            function generate_related_selection(res, container) {
                if (!res.id) return res.text;
                $(container).css('display', 'none');
                return '';
            }
            function process_related_results(data, params) {
                params.page = params.page || 1;
                var results = [];
                if (params.page === 1) {
                    results.push({
                        id: 'NEW_SERVICE_EVENT_LINK',
                        text: QATranslations.NEW_SERVICE_EVENT,
                        is_new_link: true
                    });
                }
                for (var i in data.service_events) {
                    var se_id = data.service_events[i][0],
                        se_status_id = data.service_events[i][1],
                        se_problem_description = data.service_events[i][2],
                        se_date = moment(data.service_events[i][3]).format(siteConfig.MOMENT_DATETIME_FMT),
                        se_status_name = data.service_events[i][4];
                    results.push({id: se_id, text: se_id, title: se_problem_description, date: se_date, status: se_status_name});
                    if (se_statuses) se_statuses[se_id] = se_status_id;
                }
                params.page = params.page || 1;
                return {
                    results: results,
                    pagination: {
                        more: (params.page * 30) < data.total_count
                    }
                };
            }
            
            // Ensure description container exists
            var $relatedSeDescContainer = $('#inline-related-ses-descriptions');
            if ($relatedSeDescContainer.length === 0) {
                $relatedSeDescContainer = $('<div id="inline-related-ses-descriptions" class="margin-top-10"></div>');
                $related_se.parent().append($relatedSeDescContainer);
            } else {
                $relatedSeDescContainer.empty();
            }

            var relatedSeCache = {};

            function addRelatedSesDescriptions(selected) {
                selected.sort(function(a, b) { return parseInt(b.id || 0, 10) - parseInt(a.id || 0, 10); });
                var newIds = $.map(selected, function(el) { return (el.id || "").toString(); });

                $relatedSeDescContainer.find(".related-se-desc-block").each(function(idx, el) {
                    var $el = $(el);
                    var rawId = $el.data("id");
                    var fId = rawId !== undefined ? rawId.toString() : "";
                    var loc = newIds.indexOf(fId);
                    if (loc < 0) {
                        $el.remove();
                    } else {
                        newIds.splice(loc, 1);
                        selected.splice(loc, 1);
                    }
                });

                $.each(selected, function(idx, el) {
                    var fId = el.id || el.text;
                    
                    if (relatedSeCache[fId] && relatedSeCache[fId].title) {
                        if (!el.title) el.title = relatedSeCache[fId].title;
                    } else if (el.title) {
                        relatedSeCache[fId] = { title: el.title };
                    }
                    
                    var desc = el.title || "<em>" + QATranslations.NO_DESCRIPTION_AVAILABLE + "</em>";
                    var colour = status_colours_dict ? status_colours_dict[se_statuses[fId]] : null;
                    if (!colour) colour = '#ccc';
                    
                    var html = '<div class="fault-card-hover related-se-desc-block margin-bottom-10" data-id="' + fId + '" style="display: flex; align-items: flex-start; border-left: 4px solid ' + colour + '; padding: 8px 12px; border-radius: 0 3px 3px 0; box-shadow: 0 1px 1px rgba(0,0,0,0.05);">';
                    
                    html += '  <div style="flex-shrink: 0; margin-right: 15px; display: flex; gap: 10px; align-items: center; margin-top: 2px;">';
                    html += '    <i class="fa fa-trash fa-lg text-danger remove-related-se" style="cursor: pointer;" title="' + QATranslations.REMOVE + '"></i>';
                    html += '    <a href="/servicelog/event/details/' + fId + '/" target="_blank" class="text-info"><i class="fa fa-eye fa-lg"></i></a>';
                    html += '  </div>';
                    
                    html += '  <div style="flex-grow: 1; min-width: 0;">';
                    html += '    <strong style="display: block;">' + QATranslations.ID + ': ' + fId + '</strong>';
                    html += '    <div class="margin-top-5 text-muted">' + desc + '</div>';
                    html += '  </div>';
                    
                    html += '</div>';
                    
                    $relatedSeDescContainer.append(html);
                });

                $relatedSeDescContainer.find('.remove-related-se').off('click').on('click', function() {
                    var $block = $(this).closest('.related-se-desc-block');
                    var removeId = $block.data('id').toString();
                    var currentVals = $related_se.val() || [];
                    var newVal = $.grep(currentVals, function(value) {
                        return value.toString() !== removeId;
                    });
                    $related_se.val(newVal).trigger('change');
                });
            }
            
            $related_se.select2({
                width: '100%',
                multiple: true,
                dropdownParent: s2config.dropdownParent,
                ajax: {
                    url: QAURLs.SE_SEARCHER,
                    dataType: 'json',
                    delay: '500',
                    data: function (params) {
                        var term = params.term === undefined ? "" : params.term;
                        return {
                            q: term,
                            page: params.page,
                            unit_id: $unit.val(),
                        };
                    },
                    processResults: process_related_results,
                    cache: true
                },
                escapeMarkup: function (markup) { return markup; },
                minimumInputLength: 0,
                templateResult: generate_related_result,
                templateSelection: generate_related_selection
            }).on("change", function(evt) {
                addRelatedSesDescriptions($related_se.select2('data'));
            }).on('select2:selecting', function(e) {
                if (e.params.args.data.id === 'NEW_SERVICE_EVENT_LINK') {
                    e.preventDefault();
                    $related_se.select2('close');
                    var newSeUrl = QAURLs.SL_NEW;
                    window.open(newSeUrl, '_blank');
                }
            });

            // Load initial descriptions for already selected items
            var alreadySelectedSEs = $related_se.val();
            if (alreadySelectedSEs && alreadySelectedSEs.length > 0) {
                
                // Render skeletons immediately
                if ($('#qatrack-pulse-animation').length === 0) {
                    $('head').append('<style id="qatrack-pulse-animation">@keyframes qatrack-pulse { 0% { opacity: 1; } 50% { opacity: 0.5; } 100% { opacity: 1; } }</style>');
                }

                $.each(alreadySelectedSEs, function(idx, val) {
                    var skeletonHtml = '<div class="related-se-desc-block skeleton-loader margin-bottom-10" data-skeleton="true" style="border-left: 4px solid #ddd; background-color: #f9f9f9; padding: 8px 12px; border-radius: 0 3px 3px 0; box-shadow: 0 1px 1px rgba(0,0,0,0.05);">';
                    skeletonHtml += '  <div style="font-size: 13px;">';
                    skeletonHtml += '    <i class="fa fa-spinner fa-spin text-muted" style="margin-right: 5px;"></i>';
                    skeletonHtml += '    <span class="text-muted"><strong>' + QATranslations.LOADING + '</strong></span>';
                    skeletonHtml += '  </div>';
                    skeletonHtml += '  <div class="margin-top-10 margin-bottom-5">';
                    skeletonHtml += '    <div style="height: 10px; width: 60%; background-color: #e0e0e0; border-radius: 2px; margin-bottom: 5px; animation: qatrack-pulse 1.5s infinite;"></div>';
                    skeletonHtml += '    <div style="height: 10px; width: 40%; background-color: #e0e0e0; border-radius: 2px; animation: qatrack-pulse 1.5s infinite;"></div>';
                    skeletonHtml += '  </div>';
                    skeletonHtml += '</div>';
                    $descContainer.append(skeletonHtml);
                });

                var completedSEs = [];
                $.each(alreadySelectedSEs, function(idx, val) {
                    $.ajax({
                        type: 'GET',
                        url: QAURLs.SE_SEARCHER,
                        dataType: 'json',
                        data: {
                            q: val,
                            unit_id: $unit.val() || ""
                        }
                    }).then(function(data) {
                        if (data.service_events && data.service_events.length > 0) {
                            var matched = false;
                            for (var i = 0; i < data.service_events.length; i++) {
                                if (data.service_events[i][0].toString() === val.toString()) {
                                    var se_id = data.service_events[i][0],
                                        se_status_id = data.service_events[i][1],
                                        se_problem_description = data.service_events[i][2],
                                        se_date = moment(data.service_events[i][3]).format(siteConfig.MOMENT_DATETIME_FMT),
                                        se_status_name = data.service_events[i][4];
                                    completedSEs.push({id: se_id, text: se_id, title: se_problem_description, date: se_date, status: se_status_name});
                                    if (se_statuses) se_statuses[se_id] = se_status_id;
                                    matched = true;
                                    break;
                                }
                            }
                            if (!matched) {
                                completedSEs.push({id: val, text: val});
                            }
                        } else {
                            completedSEs.push({id: val, text: val});
                        }
                        if (completedSEs.length === alreadySelectedSEs.length) {
                            addRelatedSesDescriptions(completedSEs);
                            $related_se.trigger('change.select2');
                        }
                    }, function() {
                        completedSEs.push({id: val, text: val});
                        if (completedSEs.length === alreadySelectedSEs.length) {
                            addRelatedSesDescriptions(completedSEs);
                            $related_se.trigger('change.select2');
                        }
                    });
                });
            }

            var $reviewRequiredBy = $("#id_fault-review_required_by").select2(s2config);

            $(".reviewed-by-select").select2(s2config);


            var $attachInput = $('#id_fault-attachments'),
                $attach_deletes = $('.attach-delete'),
                $attach_delete_ids = $('#id_fault-attachments_delete_ids'),
                $attach_names = $('#attachment-names');

            $attachInput.on("change", function(){
                var fnames = _.map(this.files, function(f){
                    return '<tr><td><i class="fa fa-paperclip fa-fw" aria-hidden="true"></i>' + f.name + '</td></tr>';
                }).join("");
                $attach_names.html(fnames);
            });

            $attach_deletes.change(function() {
                var deletes = [];
                $.each($attach_deletes, function(i, v) {
                    var el = $(v);
                    if (el.prop('checked')) {
                        deletes.push(el.val());
                    }
                });
                $attach_delete_ids.val(deletes.join(','));
            });
        }
        
        // Ensure HTMX swaps re-initialize the JS since RequireJS won't re-execute this module
        document.body.addEventListener('htmx:afterSettle', function(evt) {
            if ($("#id_fault-unit").length && !$("#id_fault-unit").hasClass("select2-hidden-accessible")) {
                configureFaults();
            }
        });
        
    });
});
