document.addEventListener('DOMContentLoaded', function() {
    
    // --- 1. Details Panel (Change Form) ---
    const detailsRoot = document.getElementById('testlist-builder-details-root');
    if (detailsRoot) {
        // Construct the Details card HTML
        detailsRoot.innerHTML = `
            <div class="details-card">
                <div class="details-card-header">
                    <i class="fa fa-info-circle"></i> Details
                    <span class="id-display" id="builder-id-display"></span>
                </div>
                <div class="details-card-body">
                    <div class="details-grid" id="builder-details-grid">
                        <div class="field-row" id="row-name"></div>
                        <div class="field-row" id="row-slug"></div>
                        <div class="field-row full-width" id="row-description"></div>
                        <div class="field-row full-width" id="row-warning"></div>
                        <div class="field-row full-width" id="row-javascript"></div>
                    </div>
                </div>
            </div>
        `;

        const originalFieldset = document.querySelector('fieldset.module');
        
        function moveField(srcClass, targetId, showHint=false, hintText='', warn=false, mono=false) {
            const srcRow = document.querySelector(`.form-row.field-${srcClass}`);
            if (!srcRow) return;
            
            const target = document.getElementById(targetId);
            if (!target) return;

            const label = srcRow.querySelector('label');
            if (label) {
                const newLabel = label.cloneNode(true);
                if (showHint) {
                    const hint = document.createElement('span');
                    hint.className = warn ? 'hint warn' : 'hint';
                    hint.innerHTML = hintText;
                    newLabel.appendChild(hint);
                }
                target.appendChild(newLabel);
            }

            const errors = srcRow.querySelector('.errorlist');
            if (errors) {
                target.appendChild(errors);
            }

            // Move the input/editor
            const inputContainer = srcRow.querySelector('div');
            if (inputContainer) {
                Array.from(inputContainer.childNodes).forEach(node => {
                    if (node.nodeName !== 'LABEL' && node.className !== 'help' && node.className !== 'errorlist') {
                        target.appendChild(node);
                    }
                });
            }

            const input = target.querySelector('input, textarea');
            if (input && mono) {
                input.classList.add('mono-font');
            }
        }

        // Set ID
        const idRow = document.querySelector('.form-row.field-id .readonly');
        if (idRow) {
            document.getElementById('builder-id-display').textContent = 'ID: ' + idRow.textContent;
        }

        // Move fields
        moveField('name', 'row-name');
        moveField('slug', 'row-slug', false, '', false, true);
        moveField('description', 'row-description', true, '‹/› HTML markup allowed');
        moveField('warning_message', 'row-warning', true, '<i class="fa fa-exclamation-triangle"></i> shown on failure', true);
        moveField('javascript', 'row-javascript', true, '<i class="fa fa-code"></i> runs on the perform page', false, true);

        // Hide original fieldset
        if (originalFieldset) {
            originalFieldset.style.display = 'none';
        }

        // Description Preview Toggle
        const descRow = document.getElementById('row-description');
        if (descRow) {
            const label = descRow.querySelector('label');
            if (label) {
                const toggleBtn = document.createElement('button');
                toggleBtn.type = 'button';
                toggleBtn.className = 'desc-toggle';
                toggleBtn.innerHTML = '<i class="fa fa-eye"></i> Preview';
                label.appendChild(toggleBtn);
                
                const previewBox = document.createElement('div');
                previewBox.className = 'desc-preview-box';
                descRow.appendChild(previewBox);
                
                const textarea = descRow.querySelector('textarea');
                let isPreview = false;
                
                toggleBtn.addEventListener('click', function() {
                    isPreview = !isPreview;
                    if (!textarea) return;
                    
                    // qatrack+ admin_description_editor.js wraps the textarea or uses it directly
                    // we find the immediate wrapper or just hide the textarea
                    const toHide = textarea.closest('.django-admin-description-editor') || 
                                   document.getElementById('id_description_editor_wrapper') || 
                                   textarea;
                                   
                    if (isPreview) {
                        toggleBtn.innerHTML = '<i class="fa fa-pencil"></i> Edit';
                        toHide.style.display = 'none';
                        previewBox.style.display = 'block';
                        
                        const val = textarea.value.trim();
                        if (val) {
                            previewBox.innerHTML = val;
                        } else {
                            previewBox.innerHTML = '<span class="desc-preview-empty">Nothing to preview — write a description to see how the markup renders.</span>';
                        }
                    } else {
                        toggleBtn.innerHTML = '<i class="fa fa-eye"></i> Preview';
                        toHide.style.display = '';
                        previewBox.style.display = 'none';
                    }
                });
            }
        }
    }

    // --- 2. Changelist (Index) ---
    const changelist = document.getElementById('changelist');
    if (changelist) {
        // Search Box Move
        const searchForm = document.getElementById('changelist-search');
        const searchTarget = document.getElementById('custom-search-container');
        if (searchForm && searchTarget) {
            const input = searchForm.querySelector('input[type="text"]');
            if (input) {
                input.placeholder = "Search name, slug or tags…";
            }
            const icon = document.createElement('i');
            icon.className = 'fa fa-search';
            searchTarget.appendChild(icon);
            searchTarget.appendChild(searchForm);
            
            const toolbar = document.getElementById('toolbar');
            if (toolbar) toolbar.style.display = 'none';
        }

        // Row Clicks
        const rows = document.querySelectorAll('#changelist table tbody tr');
        rows.forEach(row => {
            row.addEventListener('click', function(e) {
                if (e.target.tagName === 'A' || e.target.tagName === 'INPUT' || e.target.closest('a')) {
                    return;
                }
                const editLink = row.querySelector('.field-edit_link a');
                if (editLink) {
                    window.location.href = editLink.href;
                }
            });
        });

        // Filter Sidebar Tweaks
        const filterTitle = document.querySelector('#changelist-filter h2');
        if (filterTitle) {
            // Check if any filter is active (url has query params other than sort/p)
            // Simplified: if there's any querystring, just show clear.
            if (window.location.search.length > 1) {
                const clearBtn = document.createElement('a');
                clearBtn.href = '?';
                clearBtn.className = 'clear-filter';
                clearBtn.textContent = 'Clear';
                filterTitle.appendChild(clearBtn);
            }
        }
        
        // Hide 'All' chips unless they are the active one or the first one?
        // Requirements say: "Hide the "All" chip except render it as the first chip labelled "All""
        // Django already puts "All" as the first <li> in each <ul>
        // We just leave it, the CSS styles all <li>s as chips.
    }
});
