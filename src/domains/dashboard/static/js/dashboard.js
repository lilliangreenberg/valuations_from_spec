/* Portfolio Company Monitor - Dashboard JavaScript */
/* Minimal JS: only what HTMX cannot handle natively */

// Theme management
function toggleTheme() {
    var html = document.documentElement;
    var current = html.getAttribute('data-theme');
    var next = current === 'dark' ? 'light' : 'dark';
    html.setAttribute('data-theme', next);
    localStorage.setItem('portfolio-monitor-theme', next);
    updateThemeButton(next);
}

function updateThemeButton(theme) {
    var btn = document.getElementById('theme-toggle');
    if (btn) {
        btn.textContent = theme === 'dark' ? 'Light' : 'Dark';
    }
}

// Mobile navigation toggle
function toggleMobileNav() {
    var nav = document.getElementById('topbar-nav');
    if (nav) {
        nav.classList.toggle('mobile-open');
    }
}

// Tab switching
function switchTab(tabId, element) {
    // Update tab button states
    var tabNav = element.closest('.tab-nav');
    if (tabNav) {
        tabNav.querySelectorAll('button, a').forEach(function(btn) {
            btn.classList.remove('active');
        });
        element.classList.add('active');
    }
}

// Auto-scroll terminal output to bottom on new SSE content
document.addEventListener('htmx:sseMessage', function(event) {
    var terminal = event.target.closest('.terminal-output');
    if (terminal) {
        terminal.scrollTop = terminal.scrollHeight;
    }
});

// Handle SSE "done" event -- refresh task history and update status
document.addEventListener('htmx:sseMessage', function(event) {
    if (event.detail && event.detail.type === 'done') {
        // Trigger history refresh
        var historyEl = document.getElementById('task-history');
        if (historyEl) {
            htmx.trigger(historyEl, 'refresh');
        }
    }
});

// Loading indicator management
document.addEventListener('htmx:beforeRequest', function(event) {
    var indicator = event.target.querySelector('.htmx-indicator');
    if (indicator) {
        indicator.style.display = 'inline-block';
    }
});

document.addEventListener('htmx:afterRequest', function(event) {
    var indicator = event.target.querySelector('.htmx-indicator');
    if (indicator) {
        indicator.style.display = 'none';
    }
});

// Command form: show/hide parameter fields based on selected command
function updateCommandForm(selectElement) {
    var command = selectElement.value;
    var paramGroups = document.querySelectorAll('.command-params');
    paramGroups.forEach(function(group) {
        if (group.dataset.command === command) {
            group.style.display = 'block';
        } else {
            group.style.display = 'none';
        }
    });
}

// ================================================================
// Widget Preferences (localStorage)
// ================================================================

var WIDGET_CONFIG_KEY = 'portfolio-monitor-widgets';

function getWidgetConfig() {
    try {
        var raw = localStorage.getItem(WIDGET_CONFIG_KEY);
        if (raw) {
            return JSON.parse(raw);
        }
    } catch (e) {
        // Corrupted data, reset
    }
    return null;
}

function saveWidgetConfig(config) {
    localStorage.setItem(WIDGET_CONFIG_KEY, JSON.stringify(config));
}

function applyWidgetConfig() {
    var config = getWidgetConfig();
    if (!config) return;

    var containers = document.querySelectorAll('.widget-container[data-widget-id]');
    containers.forEach(function(el) {
        var widgetId = el.getAttribute('data-widget-id');
        if (config[widgetId] && config[widgetId].visible === false) {
            el.style.display = 'none';
        } else {
            el.style.display = '';
        }
    });

    // Sync checkboxes in customize panel
    var checkboxes = document.querySelectorAll('.widget-toggle-input[data-widget-id]');
    checkboxes.forEach(function(cb) {
        var widgetId = cb.getAttribute('data-widget-id');
        if (config[widgetId]) {
            cb.checked = config[widgetId].visible !== false;
        }
    });

    // Highlight active preset
    var preset = config._preset || 'full_dashboard';
    var presetBtns = document.querySelectorAll('.preset-btn[data-preset]');
    presetBtns.forEach(function(btn) {
        btn.classList.toggle('active', btn.getAttribute('data-preset') === preset);
    });
}

// ================================================================
// Customize Panel
// ================================================================

function openCustomizePanel() {
    var panel = document.getElementById('customize-panel');
    if (panel) {
        panel.style.display = 'block';
        applyWidgetConfig();
    }
}

function closeCustomizePanel() {
    var panel = document.getElementById('customize-panel');
    if (panel) {
        panel.style.display = 'none';
    }
}

// Layout presets
var PRESET_WIDGETS = {
    full_dashboard: ['changes', 'alerts', 'trending', 'freshness', 'activity', 'health_grid'],
    quick_glance: ['changes', 'alerts'],
    executive_summary: ['changes', 'trending', 'health_grid'],
    custom: []
};

function selectPreset(presetName) {
    var allWidgets = ['changes', 'alerts', 'trending', 'freshness', 'activity', 'health_grid'];
    var config = getWidgetConfig() || {};
    var visibleWidgets = PRESET_WIDGETS[presetName] || allWidgets;

    allWidgets.forEach(function(wid) {
        if (!config[wid]) config[wid] = {};
        config[wid].visible = visibleWidgets.indexOf(wid) !== -1;
    });
    config._preset = presetName;

    saveWidgetConfig(config);
    applyWidgetConfig();
}

function toggleWidget(widgetId) {
    var config = getWidgetConfig() || {};
    if (!config[widgetId]) config[widgetId] = {};

    var checkbox = document.querySelector('.widget-toggle-input[data-widget-id="' + widgetId + '"]');
    config[widgetId].visible = checkbox ? checkbox.checked : true;
    config._preset = 'custom';

    saveWidgetConfig(config);
    applyWidgetConfig();
}

// ================================================================
// Widget Order (SortableJS + localStorage)
// ================================================================

var WIDGET_ORDER_KEY = 'portfolio-monitor-widget-order';
var _sortableInstance = null;

function getWidgetOrder() {
    try {
        var raw = localStorage.getItem(WIDGET_ORDER_KEY);
        if (raw) {
            return JSON.parse(raw);
        }
    } catch (e) {
        // Corrupted data
    }
    return null;
}

function saveWidgetOrder(order) {
    localStorage.setItem(WIDGET_ORDER_KEY, JSON.stringify(order));
}

function applyWidgetOrder() {
    var order = getWidgetOrder();
    if (!order || !order.length) return;

    var grid = document.getElementById('widget-grid');
    if (!grid) return;

    // Reorder children based on stored order
    order.forEach(function(widgetId) {
        var el = grid.querySelector('.widget-container[data-widget-id="' + widgetId + '"]');
        if (el) {
            grid.appendChild(el);
        }
    });
}

function initSortable() {
    var grid = document.getElementById('widget-grid');
    if (!grid) return;

    // Destroy existing instance before re-init
    if (_sortableInstance) {
        _sortableInstance.destroy();
        _sortableInstance = null;
    }

    _sortableInstance = Sortable.create(grid, {
        animation: 200,
        ghostClass: 'widget-dragging',
        chosenClass: 'sortable-chosen',
        dragClass: 'sortable-drag',
        easing: 'cubic-bezier(0.25, 1, 0.5, 1)',
        onEnd: function() {
            // Read current order from DOM
            var containers = grid.querySelectorAll('.widget-container[data-widget-id]');
            var order = [];
            containers.forEach(function(el) {
                order.push(el.getAttribute('data-widget-id'));
            });
            saveWidgetOrder(order);
        }
    });
}

// ================================================================
// Change Details Expand/Collapse (LLM Flags)
// ================================================================

function toggleChangeDetails(button) {
    var card = button.closest('.card');
    if (!card) return;

    var content = card.querySelector('.change-details-content');
    if (!content) return;

    var isExpanded = button.classList.contains('expanded');

    if (isExpanded) {
        button.classList.remove('expanded');
        content.classList.remove('expanded');
    } else {
        button.classList.add('expanded');
        content.classList.add('expanded');
    }
}

// ================================================================
// Chart.js Trending Initialization
// ================================================================

var _trendingChartInstance = null;

function initTrendingChart(canvasId, config) {
    var canvas = document.getElementById(canvasId);
    if (!canvas) return;

    // Destroy existing chart before re-rendering (HTMX refresh)
    if (_trendingChartInstance) {
        _trendingChartInstance.destroy();
        _trendingChartInstance = null;
    }

    // Apply theme-aware colors
    var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    var gridColor = isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.06)';
    var textColor = isDark ? '#94a3b8' : '#6b7280';

    if (config.options && config.options.scales) {
        if (config.options.scales.x) {
            config.options.scales.x.grid = { color: gridColor };
            config.options.scales.x.ticks = { color: textColor };
        }
        if (config.options.scales.y) {
            config.options.scales.y.grid = { color: gridColor };
            config.options.scales.y.ticks = { color: textColor };
        }
    }
    if (config.options && config.options.plugins && config.options.plugins.legend) {
        config.options.plugins.legend.labels = { color: textColor };
    }

    _trendingChartInstance = new Chart(canvas, config);
}

// ================================================================
// Initialization
// ================================================================

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    // Restore theme
    var saved = localStorage.getItem('portfolio-monitor-theme') || 'light';
    document.documentElement.setAttribute('data-theme', saved);
    updateThemeButton(saved);

    // Initialize command form if present
    var commandSelect = document.getElementById('command-select');
    if (commandSelect) {
        updateCommandForm(commandSelect);
    }

    // Apply widget visibility preferences then order
    applyWidgetConfig();
    applyWidgetOrder();

    // Initialize SortableJS on widget grid
    initSortable();
});

// Reinitialize after HTMX page swap (for hx-boost navigation)
document.addEventListener('htmx:afterSettle', function() {
    var commandSelect = document.getElementById('command-select');
    if (commandSelect) {
        updateCommandForm(commandSelect);
    }

    // Re-apply widget config and order after HTMX swaps
    applyWidgetConfig();
    applyWidgetOrder();

    // Re-init sortable after HTMX swaps
    initSortable();
});
