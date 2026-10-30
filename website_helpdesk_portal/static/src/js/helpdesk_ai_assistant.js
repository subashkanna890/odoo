/**
 * Helpdesk AI Copilot (Zendesk-Inspired Production Assistant)
 * Grounded in live Odoo Helpdesk tickets, knowledge base, customers, and operations.
 */

(function() {
    'use strict';

    window.aiConversationHistory = window.aiConversationHistory || [];
    window.aiIsProcessing = false;
    window.aiLastFailedQuery = null;
    window.aiUserRole = 'employee';
    window.aiUserName = 'User';
    window.aiBotName = 'Copilot';
    window.aiAvatarUrl = '/helpdesk/ai_bot/avatar';

    function getBotAvatarHtml() {
        return '<div class="bot-avatar-tiny" title="' + escapeAiHtml(window.aiBotName || 'Copilot') + '">' +
               '<svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2L14.5 9.5L22 12L14.5 14.5L12 22L9.5 14.5L2 12L9.5 9.5L12 2Z"/></svg>' +
               '</div>';
    }

    // Helper to get active ticket ID if user is currently viewing a ticket
    window.getHelpdeskActiveTicketId = function() {
        try {
            var el = document.getElementById('empDetTicketId');
            if (el && el.value && el.value.trim() && el.value.trim() !== '0') {
                return el.value.trim();
            }
            // Check hash in URL e.g. #ticket_12 or #ticket/12
            var hash = window.location.hash || '';
            var m = hash.match(/ticket[_\/](\d+)/i);
            if (m) return m[1];
        } catch(e) {}
        return null;
    };

    // Initialize role-specific session and welcome metadata
    window.initHelpdeskAiSession = function() {
        fetch('/helpdesk/ai/session', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: JSON.stringify({ jsonrpc: '2.0', method: 'call', params: {} })
        }).then(function(res) { return res.json(); })
        .then(function(data) {
            var res = (data && data.result) ? data.result : {};
            if (res.role) window.aiUserRole = res.role;
            if (res.user_name) window.aiUserName = res.user_name;
            if (res.bot_name) window.aiBotName = res.bot_name;
            if (res.avatar_url) window.aiAvatarUrl = res.avatar_url;

            var hdrTitle = document.getElementById('aiBotHeaderTitle');
            if (hdrTitle) hdrTitle.innerText = 'Helpdesk Copilot';

            renderAiWelcomeScreen(res.welcome_message, res.suggestions);
        }).catch(function() {
            renderAiWelcomeScreen();
        });
    };

    // Render Zendesk Admin Copilot Empty State
    function renderAiWelcomeScreen(customWelcome, suggestions) {
        var container = document.getElementById('helpdeskAiBotMessages');
        if (!container) return;

        var defaultPills = [
            { key: 'find_ticket', label: 'Find a ticket' },
            { key: 'summarize_ticket', label: 'Summarize a ticket' },
            { key: 'resolve_issue', label: 'Help me resolve a customer issue' },
            { key: 'search_kb', label: 'Search the knowledge base' },
            { key: 'draft_reply', label: 'Draft a customer reply' },
            { key: 'analyze_unresolved', label: 'Analyze unresolved tickets' }
        ];

        var pills = (suggestions && suggestions.length > 0) ? suggestions : defaultPills;

        var pillsHtml = pills.map(function(c) {
            return '<button type="button" class="copilot-pill-btn" onclick="sendHelpdeskAiAction(\'' + c.key + '\', \'' + c.label.replace(/'/g, "\\'") + '\')">' +
                   escapeAiHtml(c.label) +
                   '</button>';
        }).join('');

        container.innerHTML = 
            '<div class="copilot-empty-state" id="copilotEmptyState">' +
                '<div class="copilot-sparkle-hero">' +
                    '<svg width="26" height="26" viewBox="0 0 24 24" fill="currentColor">' +
                        '<path d="M12 2L14.5 9.5L22 12L14.5 14.5L12 22L9.5 14.5L2 12L9.5 9.5L12 2Z"/>' +
                    '</svg>' +
                '</div>' +
                '<h3 class="copilot-hero-heading">How can I help?</h3>' +
                '<div class="copilot-pills-list">' + pillsHtml + '</div>' +
                '<div class="copilot-ai-disclaimer">' +
                    '<strong>Powered by AI</strong>' +
                    'AI content can be inaccurate or misleading. Review it carefully.' +
                '</div>' +
            '</div>';
    }

    // Open Chat Drawer
    window.openHelpdeskAiBot = function() {
        var modal = document.getElementById('helpdeskAiBotModal');
        if (!modal) return;
        modal.classList.add('ai-open');
        modal.style.setProperty('display', 'flex', 'important');
        document.body.classList.add('emp-copilot-open');
        var vp = document.querySelector('.emp-viewport');
        if (vp) vp.classList.add('emp-copilot-open');
        setTimeout(function() {
            var inp = document.getElementById('helpdeskAiBotInput');
            if (inp) {
                inp.focus();
                autoExpandCopilotInput(inp);
            }
        }, 60);
    };

    // Close Chat Drawer
    window.closeHelpdeskAiBot = function() {
        var modal = document.getElementById('helpdeskAiBotModal');
        if (!modal) return;
        modal.classList.remove('ai-open', 'emp-copilot-expanded');
        modal.style.setProperty('display', 'none', 'important');
        document.body.classList.remove('emp-copilot-open', 'emp-copilot-fullscreen');
        var vp = document.querySelector('.emp-viewport');
        if (vp) vp.classList.remove('emp-copilot-open', 'emp-copilot-fullscreen');
        var btn = document.getElementById('copilotExpandToggleBtn');
        if (btn) {
            btn.title = 'Expand to full screen';
            btn.setAttribute('aria-label', 'Expand to full screen');
            btn.innerHTML = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/></svg>';
        }
    };

    // Toggle Expand / Collapse Drawer View
    window.toggleExpandHelpdeskAiBot = function() {
        var modal = document.getElementById('helpdeskAiBotModal');
        if (!modal) return;
        var isExpanded = modal.classList.toggle('emp-copilot-expanded');
        if (isExpanded) {
            document.body.classList.add('emp-copilot-fullscreen');
            var vp = document.querySelector('.emp-viewport');
            if (vp) vp.classList.add('emp-copilot-fullscreen');
        } else {
            document.body.classList.remove('emp-copilot-fullscreen');
            var vp = document.querySelector('.emp-viewport');
            if (vp) vp.classList.remove('emp-copilot-fullscreen');
        }
        var btn = document.getElementById('copilotExpandToggleBtn');
        if (btn) {
            btn.title = isExpanded ? 'Exit full screen' : 'Expand to full screen';
            btn.setAttribute('aria-label', isExpanded ? 'Exit full screen' : 'Expand to full screen');
            btn.innerHTML = isExpanded
                ? '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="4 14 10 14 10 20"/><polyline points="20 10 14 10 14 4"/><line x1="14" y1="10" x2="21" y2="3"/><line x1="10" y1="14" x2="3" y2="21"/></svg>'
                : '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/></svg>';
        }
    };

    // Helper to open ticket directly in workspace by ID or code
    window.openEmpTicketById = function(ticketIdOrCode) {
        if (!ticketIdOrCode) return;
        var clean = String(ticketIdOrCode).replace(/^[#\s]+/, '').trim();
        var numMatch = clean.match(/\d+/);
        var numericId = numMatch ? parseInt(numMatch[0], 10) : null;

        // 1. Check if row exists in current table
        var row = null;
        if (numericId) {
            row = document.querySelector('[data-ticket-id="' + numericId + '"]') ||
                  document.getElementById('empTicketRow_' + numericId) ||
                  document.getElementById('ticketRow_' + numericId);
        }
        if (!row && clean) {
            row = document.querySelector('[data-code="' + clean + '"]') ||
                  document.querySelector('[data-code="#' + clean + '"]');
        }

        if (row && typeof openEmpTicketRow === 'function') {
            openEmpTicketRow(row);
            return;
        }

        // 2. Call openEmpTicketDetail directly
        if (typeof openEmpTicketDetail === 'function' && numericId) {
            openEmpTicketDetail(numericId);
            return;
        }

        // 3. Customer portal notification helper
        if (typeof openTicketFromNotification === 'function' && numericId) {
            openTicketFromNotification(numericId);
            return;
        }

        // 4. Switch to tickets tab and select
        if (typeof switchEmpTab === 'function') {
            switchEmpTab('tickets');
            if (numericId) {
                setTimeout(function() {
                    var r = document.querySelector('[data-ticket-id="' + numericId + '"]') ||
                            document.getElementById('empTicketRow_' + numericId);
                    if (r && typeof openEmpTicketRow === 'function') {
                        openEmpTicketRow(r);
                    }
                }, 200);
            }
        }
    };

    // Toggle Chat Window
    var lastToggleTick = 0;
    window.toggleHelpdeskAiBot = function(e) {
        if (e) {
            try {
                if (e.preventDefault) e.preventDefault();
                if (e.stopPropagation) e.stopPropagation();
                if (e.stopImmediatePropagation) e.stopImmediatePropagation();
            } catch(ex) {}
        }
        var now = Date.now();
        if (now - lastToggleTick < 250) return false;
        lastToggleTick = now;

        var modal = document.getElementById('helpdeskAiBotModal');
        if (!modal) return false;

        var isClosed = (!modal.classList.contains('ai-open') && modal.style.display !== 'flex');
        if (isClosed) {
            window.openHelpdeskAiBot();
        } else {
            window.closeHelpdeskAiBot();
        }
        return false;
    };

    // Reset Chat to Fresh Conversation
    window.resetHelpdeskAiBot = function() {
        window.aiConversationHistory = [];
        window.aiIsProcessing = false;
        window.aiLastFailedQuery = null;
        renderAiWelcomeScreen();
        var inp = document.getElementById('helpdeskAiBotInput');
        if (inp) {
            inp.value = '';
            autoExpandCopilotInput(inp);
            inp.focus();
        }
    };

    // Quick Action Pill Click Handler
    window.sendHelpdeskAiAction = function(key, label) {
        if (window.aiIsProcessing) return;
        var emptyState = document.getElementById('copilotEmptyState');
        if (emptyState && emptyState.parentNode) {
            emptyState.parentNode.removeChild(emptyState);
        }
        appendUserAiMessage(label);
        queryHelpdeskAiBot(label, key);
    };

    // Auto-grow textarea handler
    window.autoExpandCopilotInput = function(ta) {
        if (!ta) return;
        ta.style.height = 'auto';
        var newH = Math.min(ta.scrollHeight, 120);
        ta.style.height = Math.max(24, newH) + 'px';
    };

    // Keydown handler: Enter sends, Shift+Enter for newline
    window.handleCopilotTextareaKey = function(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleHelpdeskAiSubmit(e);
        }
    };

    // Submit Composer Form
    window.handleHelpdeskAiSubmit = function(e) {
        if (e && e.preventDefault) e.preventDefault();
        if (window.aiIsProcessing) return false;
        var inp = document.getElementById('helpdeskAiBotInput');
        if (!inp) return false;
        var msg = inp.value.trim();
        if (!msg) return false;
        inp.value = '';
        autoExpandCopilotInput(inp);

        var emptyState = document.getElementById('copilotEmptyState');
        if (emptyState && emptyState.parentNode) {
            emptyState.parentNode.removeChild(emptyState);
        }

        appendUserAiMessage(msg);
        queryHelpdeskAiBot(msg, '');
        return false;
    };

    function appendUserAiMessage(text) {
        var container = document.getElementById('helpdeskAiBotMessages');
        if (!container) return;
        var timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        var div = document.createElement('div');
        div.className = 'bot-msg-row bot-msg-out';
        div.innerHTML = '<div class="bot-bubble">' + escapeAiHtml(text) + '<div class="bot-meta-bar"><span>' + timeStr + '</span></div></div>';
        container.appendChild(div);
        container.scrollTop = container.scrollHeight;

        window.aiConversationHistory.push({
            role: 'user',
            content: text
        });
    }

    function escapeAiHtml(str) {
        return (str || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function parseMarkdownTables(text) {
        var tableRegex = /((?:^[ \t]*\|[^\n]+\|[ \t]*\r?\n)+(?:^[ \t]*\|[\s\-:|]+\|[ \t]*\r?\n)(?:^[ \t]*\|[^\n]+\|[ \t]*(?:\r?\n|$))+)/gm;
        return text.replace(tableRegex, function(match) {
            var rawLines = match.trim().split(/\r?\n/);
            if (rawLines.length < 3) return match;
            var headerCols = rawLines[0].trim().replace(/^\||\|$/g, '').split('|').map(function(c) { return c.trim(); });
            var rows = rawLines.slice(2);

            var isTicketTable = false;
            var tktColIdx = -1;
            var subjColIdx = -1;
            var custColIdx = -1;
            var prioColIdx = -1;
            var stageColIdx = -1;
            var assignColIdx = -1;

            headerCols.forEach(function(col, idx) {
                var c = col.toLowerCase();
                if (c.indexOf('ticket') > -1 || c === '#' || c.indexOf('code') > -1 || c.indexOf('id') > -1) {
                    if (tktColIdx === -1) tktColIdx = idx;
                } else if (c.indexOf('subject') > -1 || c.indexOf('title') > -1 || c.indexOf('name') > -1 || c.indexOf('issue') > -1) {
                    if (subjColIdx === -1) subjColIdx = idx;
                } else if (c.indexOf('customer') > -1 || c.indexOf('client') > -1 || c.indexOf('requester') > -1) {
                    if (custColIdx === -1) custColIdx = idx;
                } else if (c.indexOf('priority') > -1) {
                    if (prioColIdx === -1) prioColIdx = idx;
                } else if (c.indexOf('stage') > -1 || c.indexOf('status') > -1 || c.indexOf('state') > -1) {
                    if (stageColIdx === -1) stageColIdx = idx;
                } else if (c.indexOf('assign') > -1 || c.indexOf('agent') > -1 || c.indexOf('owner') > -1) {
                    if (assignColIdx === -1) assignColIdx = idx;
                }
            });

            if (tktColIdx !== -1 || (subjColIdx !== -1 && (stageColIdx !== -1 || prioColIdx !== -1))) {
                isTicketTable = true;
            }

            var parsedRows = rows.map(function(r) {
                return r.trim().replace(/^\||\|$/g, '').split('|').map(function(c) { return c.trim(); });
            });

            // Build full HTML table (used in wide / full-screen mode)
            var tableHtml = '<div class="ai-table-wrap copilot-table-container"><table class="ai-md-table"><thead><tr>';
            headerCols.forEach(function(col) {
                tableHtml += '<th>' + escapeAiHtml(col) + '</th>';
            });
            tableHtml += '</tr></thead><tbody>';
            parsedRows.forEach(function(cols) {
                tableHtml += '<tr>';
                cols.forEach(function(cell, idx) {
                    var cellText = escapeAiHtml(cell);
                    if (idx === tktColIdx || (tktColIdx === -1 && idx === 0 && /^#?[a-zA-Z]*\d+/.test(cell))) {
                        var cleanTktId = cell.replace(/[^0-9a-zA-Z_\-#]/g, '');
                        cellText = '<a href="javascript:void(0)" onclick="window.openEmpTicketById(\'' + cleanTktId.replace(/'/g, "\\'") + '\')" style="color:#6A2B86;font-weight:700;text-decoration:none;" title="Open ticket in workspace">' + cellText + '</a>';
                    }
                    tableHtml += '<td>' + cellText + '</td>';
                });
                tableHtml += '</tr>';
            });
            tableHtml += '</tbody></table></div>';

            if (!isTicketTable) {
                return '\n<div class="ai-table-wrap"><table class="ai-md-table">' + tableHtml.replace(/<div[^>]*>|<\/div>/g, '') + '</div>\n';
            }

            // Build responsive cards list for 380px panel
            var cardsHtml = '<div class="copilot-ticket-cards-list">';
            parsedRows.forEach(function(cols) {
                var tktNum = (tktColIdx !== -1 && cols[tktColIdx]) ? cols[tktColIdx] : '';
                var subj = (subjColIdx !== -1 && cols[subjColIdx]) ? cols[subjColIdx] : (cols[0] || 'Ticket');
                var cust = (custColIdx !== -1 && cols[custColIdx]) ? cols[custColIdx] : '';
                var prio = (prioColIdx !== -1 && cols[prioColIdx]) ? cols[prioColIdx] : '';
                var stage = (stageColIdx !== -1 && cols[stageColIdx]) ? cols[stageColIdx] : '';
                var assignee = (assignColIdx !== -1 && cols[assignColIdx]) ? cols[assignColIdx] : '';

                var cleanId = (tktNum || subj).replace(/[^0-9a-zA-Z_\-#]/g, '');

                cardsHtml += '<div class="copilot-ticket-card" onclick="window.openEmpTicketById(\'' + cleanId.replace(/'/g, "\\'") + '\')">';
                cardsHtml += '<div class="copilot-ticket-card-header">';
                cardsHtml += '<span class="copilot-ticket-id-tag">' + escapeAiHtml(tktNum || ('#' + cleanId)) + '</span>';
                cardsHtml += '<div class="copilot-ticket-badges">';
                if (stage) {
                    var stClass = 'stage-new';
                    var stLow = stage.toLowerCase();
                    if (stLow.indexOf('progress') > -1 || stLow.indexOf('open') > -1) stClass = 'stage-progress';
                    else if (stLow.indexOf('hold') > -1 || stLow.indexOf('wait') > -1) stClass = 'stage-hold';
                    else if (stLow.indexOf('rot') > -1 || stLow.indexOf('overdue') > -1) stClass = 'stage-rotting';
                    else if (stLow.indexOf('resolv') > -1 || stLow.indexOf('done') > -1 || stLow.indexOf('close') > -1) stClass = 'stage-resolved';
                    cardsHtml += '<span class="copilot-badge ' + stClass + '">' + escapeAiHtml(stage) + '</span>';
                }
                if (prio) {
                    var prClass = 'prio-normal';
                    var prLow = prio.toLowerCase();
                    if (prLow.indexOf('urgent') > -1 || prLow.indexOf('critical') > -1 || prLow === '3') prClass = 'prio-urgent';
                    else if (prLow.indexOf('high') > -1 || prLow === '2') prClass = 'prio-high';
                    else if (prLow.indexOf('low') > -1) prClass = 'prio-low';
                    cardsHtml += '<span class="copilot-badge ' + prClass + '">' + escapeAiHtml(prio) + '</span>';
                }
                cardsHtml += '</div></div>';

                cardsHtml += '<div class="copilot-ticket-card-subject">' + escapeAiHtml(subj) + '</div>';

                if (cust || assignee) {
                    cardsHtml += '<div class="copilot-ticket-card-footer">';
                    if (cust) {
                        cardsHtml += '<span>👤 ' + escapeAiHtml(cust) + '</span>';
                    } else {
                        cardsHtml += '<span></span>';
                    }
                    if (assignee) {
                        cardsHtml += '<span>Agent: ' + escapeAiHtml(assignee) + '</span>';
                    }
                    cardsHtml += '</div>';
                }
                cardsHtml += '</div>';
            });
            cardsHtml += '</div>';

            return '\n' + cardsHtml + tableHtml + '\n';
        });
    }

    function formatAiMarkdown(text) {
        if (!text) return '';
        var s = text;

        s = parseMarkdownTables(s);

        // Headings
        s = s.replace(/^#### (.*$)/gim, '<h6 style="font-size:13px;font-weight:700;margin:6px 0 2px 0;color:#0F172A;">$1</h6>');
        s = s.replace(/^### (.*$)/gim, '<h6 style="font-size:13.5px;font-weight:700;margin:6px 0 3px 0;color:#0F172A;">$1</h6>');
        s = s.replace(/^## (.*$)/gim, '<h5 style="font-size:14px;font-weight:700;margin:8px 0 4px 0;color:#0F172A;">$1</h5>');

        // Bold and Italic
        s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
        s = s.replace(/\*([^*]+)\*/g, '<em>$1</em>');

        // Code blocks & inline code
        s = s.replace(/```([^`]+)```/g, '<pre style="background:#0F172A;color:#F8FAFC;padding:10px 12px;border-radius:6px;font-size:12px;overflow-x:auto;margin:6px 0;white-space:pre-wrap;"><code>$1</code></pre>');
        s = s.replace(/`([^`]+)`/g, '<code style="background:rgba(106,43,134,0.08);color:#6A2B86;padding:1px 5px;border-radius:4px;font-size:12px;font-weight:600;">$1</code>');

        // Blockquotes
        s = s.replace(/^[ \t]*>[ \t]*(.+)$/gm, '<blockquote style="border-left: 3px solid #6A2B86; background: #F8FAFC; margin: 4px 0; padding: 6px 12px; color: #475569; font-size: 12.5px; border-radius: 0 4px 4px 0;">$1</blockquote>');

        // Numbered / ordered lists
        s = s.replace(/^[ \t]*(\d+)\.[ \t]+(.+)$/gm, '<div style="display:flex;align-items:flex-start;gap:6px;margin:2px 0;"><span style="color:#6A2B86;font-weight:600;min-width:16px;">$1.</span><span style="line-height:1.45;">$2</span></div>');

        // Bullet lists
        s = s.replace(/^[ \t]*[•\-\*][ \t]+(.+)$/gm, '<div style="display:flex;align-items:flex-start;gap:6px;margin:2px 0;"><span style="color:#6A2B86;font-weight:bold;line-height:1.45;">•</span><span style="line-height:1.45;">$1</span></div>');

        // Paragraphs & breaks
        s = s.replace(/\n\n/g, '<div style="height:6px;"></div>');
        s = s.replace(/\n/g, '<br/>');
        return s;
    }

    window.copyAiMessage = function(btn) {
        try {
            var bubble = btn.closest('.bot-bubble');
            if (!bubble) return;
            var rawText = bubble.innerText.replace(/Copy|Retry|\d{1,2}:\d{2}\s*(?:AM|PM)?/gi, '').trim();
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(rawText);
            } else {
                var ta = document.createElement('textarea');
                ta.value = rawText;
                document.body.appendChild(ta);
                ta.select();
                document.execCommand('copy');
                document.body.removeChild(ta);
            }
            btn.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" style="vertical-align:middle;margin-right:3px;"><polyline points="20 6 9 17 4 12"/></svg> <span>Copied!</span>';
            setTimeout(function() {
                btn.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle;margin-right:3px;"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg> <span>Copy</span>';
            }, 2000);
        } catch(e) {
            console.warn('Copy error:', e);
        }
    };

    window.retryLastAiQuery = function() {
        if (window.aiLastFailedQuery) {
            var q = window.aiLastFailedQuery;
            queryHelpdeskAiBot(q.msg, q.key);
        }
    };

    function streamAiMessageToBubble(bubbleEl, fullHtml, onDone) {
        var container = document.getElementById('helpdeskAiBotMessages');
        if (fullHtml.indexOf('<table') > -1 || fullHtml.indexOf('<pre') > -1) {
            bubbleEl.innerHTML = fullHtml;
            if (container) container.scrollTop = container.scrollHeight;
            if (onDone) onDone();
            return;
        }

        bubbleEl.innerHTML = '';
        var cursorSpan = document.createElement('span');
        cursorSpan.style.cssText = 'display:inline-block;width:6px;height:13px;background:#6A2B86;margin-left:3px;vertical-align:middle;animation:aiCursorBlink 0.7s infinite;';

        var tokens = fullHtml.match(/(<[^>]+>|[^<>\s]+|\s+)/g) || [fullHtml];
        var tokenIdx = 0;
        var accumulated = '';

        var timer = setInterval(function() {
            if (tokenIdx < tokens.length) {
                var batch = 0;
                while (tokenIdx < tokens.length && batch < 4) {
                    accumulated += tokens[tokenIdx];
                    tokenIdx++;
                    batch++;
                }
                bubbleEl.innerHTML = accumulated;
                bubbleEl.appendChild(cursorSpan);
                if (container) container.scrollTop = container.scrollHeight;
            } else {
                clearInterval(timer);
                bubbleEl.innerHTML = fullHtml;
                if (container) container.scrollTop = container.scrollHeight;
                if (onDone) onDone();
            }
        }, 12);
    }

    function executePortalScreenAction(act) {
        if (!act) return;
        try {
            if (act.type === 'open_ticket') {
                if (typeof openAixoDetail === 'function') {
                    openAixoDetail(
                        act.ticket_id,
                        act.ticket_code,
                        act.ticket_name,
                        act.ticket_project,
                        act.ticket_priority,
                        act.ticket_desc,
                        act.ticket_stage,
                        act.ticket_category,
                        act.ticket_tags || ''
                    );
                } else if (typeof window.openEmpTicketDetailById === 'function') {
                    window.openEmpTicketDetailById(act.ticket_id);
                }
            } else if (act.type === 'open_new_ticket') {
                if (typeof switchAixoTab === 'function') {
                    switchAixoTab('create_ticket');
                } else if (typeof activateScreen === 'function') {
                    activateScreen('empScrCreateTicket');
                } else if (typeof switchEmpTab === 'function') {
                    switchEmpTab('create_ticket');
                }
            } else if (act.type === 'ticket_created') {
                if (typeof switchAixoTab === 'function') {
                    switchAixoTab('tickets');
                } else if (typeof switchEmpTab === 'function') {
                    switchEmpTab('tickets');
                }
                if (act.ticket_id && typeof window.openEmpTicketDetailById === 'function') {
                    setTimeout(function() {
                        window.openEmpTicketDetailById(act.ticket_id);
                    }, 250);
                }
            } else if (act.type === 'switch_tab' && act.tab) {
                if (typeof switchAixoTab === 'function') {
                    switchAixoTab(act.tab);
                } else if (typeof switchEmpTab === 'function') {
                    switchEmpTab(act.tab);
                }
            }
        } catch(e) {
            console.warn('Portal screen action error:', e);
        }
    }

    window.confirmAiTicketCreation = function(btn, title, desc, cat, prio) {
        btn.disabled = true;
        btn.innerText = 'Creating ticket...';
        var container = document.getElementById('helpdeskAiBotMessages');

        fetch('/helpdesk/ai/create_ticket', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: JSON.stringify({
                jsonrpc: '2.0',
                method: 'call',
                params: {
                    name: title,
                    description: desc,
                    category: cat || 'technical',
                    priority: prio || '0'
                }
            })
        }).then(function(res) { return res.json(); })
        .then(function(data) {
            var resData = (data && data.result) ? data.result : {};
            btn.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" style="vertical-align:middle;margin-right:2px;"><polyline points="20 6 9 17 4 12"/></svg> Submitted';
            if (resData.trigger_action) {
                executePortalScreenAction(resData.trigger_action);
            }

            var botDiv = document.createElement('div');
            botDiv.className = 'bot-msg-row bot-msg-in';
            var bubbleDiv = document.createElement('div');
            bubbleDiv.className = 'bot-bubble';
            var timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            bubbleDiv.innerHTML = formatAiMarkdown(resData.reply_text || 'Ticket created successfully!') + '<div class="bot-meta-bar"><span>' + timeStr + '</span></div>';
            botDiv.innerHTML = getBotAvatarHtml();
            botDiv.appendChild(bubbleDiv);
            if (container) {
                container.appendChild(botDiv);
                container.scrollTop = container.scrollHeight;
            }
        }).catch(function(err) {
            btn.disabled = false;
            btn.innerText = 'Retry Submission';
        });
    };

    function queryHelpdeskAiBot(msg, key) {
        window.aiIsProcessing = true;
        var sendBtn = document.getElementById('helpdeskAiSendBtn');
        if (sendBtn) sendBtn.disabled = true;

        var container = document.getElementById('helpdeskAiBotMessages');
        var typingDiv = document.createElement('div');
        typingDiv.className = 'bot-msg-row bot-msg-in typing-row';
        typingDiv.innerHTML = getBotAvatarHtml() + '<div class="bot-bubble text-muted" style="font-size:12.5px;"><em>' + escapeAiHtml(window.aiBotName || 'Copilot') + ' is analyzing...</em></div>';
        if (container) {
            container.appendChild(typingDiv);
            container.scrollTop = container.scrollHeight;
        }

        var activeTktId = window.getHelpdeskActiveTicketId();

        fetch('/helpdesk/ai/query', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: JSON.stringify({
                jsonrpc: '2.0',
                method: 'call',
                params: {
                    message: msg,
                    action_key: key,
                    role: window.aiUserRole,
                    history: window.aiConversationHistory,
                    active_ticket_id: activeTktId
                }
            })
        }).then(function(res) { return res.json(); })
        .then(function(data) {
            window.aiIsProcessing = false;
            if (sendBtn) sendBtn.disabled = false;
            if (typingDiv && typingDiv.parentNode) typingDiv.parentNode.removeChild(typingDiv);
            var result = (data && data.result) ? data.result : {};
            var replyText = result.reply_text;
            if (!replyText || !replyText.trim()) {
                replyText = 'I have analyzed your request against our Helpdesk records. How can I further assist you with your tickets or documentation?';
            }
            var formattedHtml = formatAiMarkdown(replyText);
            var act = result.trigger_action;
            var prev = result.ticket_preview;
            var sources = result.sources || [];

            if (act) {
                executePortalScreenAction(act);
            }

            var botDiv = document.createElement('div');
            botDiv.className = 'bot-msg-row bot-msg-in';
            var bubbleDiv = document.createElement('div');
            bubbleDiv.className = 'bot-bubble';
            botDiv.innerHTML = getBotAvatarHtml();
            botDiv.appendChild(bubbleDiv);
            if (container) {
                container.appendChild(botDiv);
                container.scrollTop = container.scrollHeight;
            }

            streamAiMessageToBubble(bubbleDiv, formattedHtml, function() {
                var timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
                var metaDiv = document.createElement('div');
                metaDiv.className = 'bot-meta-bar';
                metaDiv.innerHTML = '<div class="bot-bubble-actions"><button type="button" class="btn-bubble-action" onclick="copyAiMessage(this)"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle;margin-right:3px;"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg><span>Copy</span></button></div><span>' + timeStr + '</span>';
                bubbleDiv.appendChild(metaDiv);

                // Render Sources Citations
                if (sources && sources.length > 0) {
                    var sourcesDiv = document.createElement('div');
                    sourcesDiv.style.cssText = 'margin-top: 8px; padding-top: 6px; border-top: 1px dashed #E2E8F0; font-size: 11px; color: #64748B;';
                    var sourcesHtml = '<strong>Sources &amp; Documentation:</strong><div style="display:flex;flex-wrap:wrap;gap:4px;margin-top:4px;">';
                    sources.forEach(function(s) {
                        sourcesHtml += '<span style="background:#F3E8FF;color:#6A2B86;padding:2px 8px;border-radius:12px;border:1px solid #E9D5FF;display:inline-flex;align-items:center;gap:4px;"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>' + escapeAiHtml(s.title) + '</span>';
                    });
                    sourcesHtml += '</div>';
                    sourcesDiv.innerHTML = sourcesHtml;
                    bubbleDiv.appendChild(sourcesDiv);
                }

                // Render Interactive Ticket Preview Card
                if (prev) {
                    var card = document.createElement('div');
                    card.className = 'ai-ticket-preview-card';
                    card.innerHTML = 
                        '<div class="ai-ticket-preview-field"><span class="ai-ticket-preview-label">TITLE:</span> <span class="ai-ticket-preview-val">' + escapeAiHtml(prev.name) + '</span></div>' +
                        '<div class="ai-ticket-preview-field"><span class="ai-ticket-preview-label">CATEGORY:</span> <span class="ai-ticket-preview-val">' + escapeAiHtml(prev.category) + '</span></div>' +
                        '<div class="ai-ticket-preview-field"><span class="ai-ticket-preview-label">PRIORITY:</span> <span class="ai-ticket-preview-val">' + escapeAiHtml(prev.priority) + '</span></div>' +
                        '<div class="ai-ticket-preview-field"><span class="ai-ticket-preview-label">DESCRIPTION:</span> <span class="ai-ticket-preview-val">' + escapeAiHtml(prev.description) + '</span></div>' +
                        '<button type="button" class="ai-preview-confirm-btn" onclick="confirmAiTicketCreation(this, \'' + escapeAiHtml(prev.name) + '\', \'' + escapeAiHtml(prev.description) + '\', \'' + escapeAiHtml(prev.category) + '\', \'' + escapeAiHtml(prev.priority) + '\')">Confirm &amp; Create Ticket</button>';
                    bubbleDiv.appendChild(card);
                    if (container) container.scrollTop = container.scrollHeight;
                }

                window.aiConversationHistory.push({
                    role: 'model',
                    content: replyText
                });
            });

        }).catch(function(err) {
            window.aiIsProcessing = false;
            if (sendBtn) sendBtn.disabled = false;
            window.aiLastFailedQuery = { msg: msg, key: key };
            if (typingDiv && typingDiv.parentNode) typingDiv.parentNode.removeChild(typingDiv);
            var errDiv = document.createElement('div');
            errDiv.className = 'bot-msg-row bot-msg-in';
            errDiv.innerHTML = getBotAvatarHtml() + '<div class="bot-bubble" style="color:#DC2626;border:1px solid #FCA5A5;">Unable to reach Helpdesk Copilot. <button type="button" class="btn-bubble-action" onclick="retryLastAiQuery()" style="color:#6A2B86;font-weight:600;margin-left:6px;display:inline-flex;align-items:center;gap:3px;"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/></svg> Retry</button></div>';
            if (container) {
                container.appendChild(errDiv);
                container.scrollTop = container.scrollHeight;
            }
        });
    }

    function setupAiLauncher() {
        var headerBtn = document.getElementById('btnOpenEmpCopilot');
        if (headerBtn) {
            headerBtn.onclick = function(e) {
                window.toggleHelpdeskAiBot(e);
            };
        }
        var legacyBtn = document.getElementById('helpdeskAiBotBtn');
        if (legacyBtn) {
            legacyBtn.onclick = function(e) {
                window.toggleHelpdeskAiBot(e);
            };
        }

        var inputEl = document.getElementById('helpdeskAiBotInput');
        if (inputEl) {
            inputEl.oninput = function() {
                autoExpandCopilotInput(this);
            };
            inputEl.onkeydown = function(e) {
                handleCopilotTextareaKey(e);
            };
        }

        window.initHelpdeskAiSession();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', setupAiLauncher);
    } else {
        setupAiLauncher();
    }
})();
