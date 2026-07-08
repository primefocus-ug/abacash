/* ABA Uganda — main JavaScript */

/* ----------------------------------------------------------------
   Sidebar toggle (mobile)
   ---------------------------------------------------------------- */
document.addEventListener('DOMContentLoaded', () => {
  const sidebar   = document.getElementById('sidebar');
  const toggleBtn = document.getElementById('sidebar-toggle');
  const overlay   = document.getElementById('sidebar-overlay');

  const today = new Date();
  const todayDate = today.toISOString().split('T')[0];
  const todayDateTime = `${todayDate}T${String(today.getHours()).padStart(2, '0')}:${String(today.getMinutes()).padStart(2, '0')}`;

  document.querySelectorAll('input[type="date"], input[type="datetime-local"]').forEach(input => {
    if (!input.value) {
      input.value = input.type === 'datetime-local' ? todayDateTime : todayDate;
    }
  });

  if (toggleBtn && sidebar) {
    toggleBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      sidebar.classList.toggle('open');
      if (overlay) overlay.classList.toggle('active');
    });
  }
  
  if (overlay) {
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) {
        sidebar.classList.remove('open');
        overlay.classList.remove('active');
        document.body.style.overflow = '';
      }
    });
  }

  // Close sidebar when clicking a nav link on mobile
  document.querySelectorAll('.nav-link').forEach(link => {
    link.addEventListener('click', () => {
      if (sidebar && window.innerWidth <= 768) {
        sidebar.classList.remove('open');
        if (overlay) overlay.classList.remove('active');
        document.body.style.overflow = '';
      }
    });
  });
});

/* Global function for backward compatibility */
function toggleSidebar() {
  const sidebar = document.getElementById('sidebar');
  const overlay = document.getElementById('sidebar-overlay');
  if (sidebar) sidebar.classList.toggle('open');
  if (overlay) overlay.classList.toggle('active');
  if (sidebar && sidebar.classList.contains('open')) {
    document.body.style.overflow = 'hidden';
  } else {
    document.body.style.overflow = '';
  }
}

function closeSidebar() {
  const sidebar = document.getElementById('sidebar');
  const overlay = document.getElementById('sidebar-overlay');
  if (sidebar) sidebar.classList.remove('open');
  if (overlay) overlay.classList.remove('active');
  document.body.style.overflow = '';
}

/* ----------------------------------------------------------------
   Extend schedule entry (prompt + POST)
   ---------------------------------------------------------------- */
function getCookie(name) {
  const v = document.cookie.match('(^|;)\\s*' + name + '\\s*=\\s*([^;]+)');
  return v ? v.pop() : '';
}

document.addEventListener('click', e => {
  const btn = e.target.closest('.btn-extend-schedule');
  if (!btn) return;
  const scheduleId = btn.dataset.scheduleId;
  if (!scheduleId) return;

  const newDate = prompt('Enter new due date (YYYY-MM-DD):');
  if (!newDate) return;
  const reason = prompt('Reason for extension (required):');
  if (!reason) { alert('Extension reason is required.'); return; }

  const url = `/loans/schedule/${scheduleId}/extend/`;
  const form = new FormData();
  form.append('new_due_date', newDate);
  form.append('reason', reason);

  fetch(url, {
    method: 'POST',
    headers: { 'X-CSRFToken': getCookie('csrftoken') },
    body: form,
  }).then(r => {
    if (r.redirected) {
      window.location = r.url;
    } else if (r.ok) {
      window.location.reload();
    } else {
      r.text().then(t => { alert('Failed to extend schedule entry.'); console.error(t); });
    }
  }).catch(err => { alert('Network error'); console.error(err); });
});

/* ----------------------------------------------------------------
   Theme toggle (dark/light)
   ---------------------------------------------------------------- */
document.addEventListener('DOMContentLoaded', () => {
  const btn = document.getElementById('theme-toggle');
  const label = document.getElementById('theme-toggle-label');
  if (!btn) return;

  const updateToggleUI = (theme) => {
    if (label) label.textContent = theme === 'light' ? 'Dark' : 'Light';
  };

  const setTheme = (theme) => {
    document.documentElement.setAttribute('data-theme', theme);
    try { window.localStorage.setItem('aba_theme', theme); } catch (e) { /* ignore */ }
    updateToggleUI(theme);
  };

  const storedTheme = (() => {
    try { return window.localStorage.getItem('aba_theme'); } catch (e) { return null; }
  })();
  const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  const initialTheme = storedTheme || (prefersDark ? 'dark' : 'light');
  setTheme(initialTheme);

  btn.addEventListener('click', () => {
    const currentTheme = document.documentElement.getAttribute('data-theme') || 'light';
    setTheme(currentTheme === 'light' ? 'dark' : 'light');
  });
});

/* ----------------------------------------------------------------
   Auto-dismiss flash messages after 4 seconds
   ---------------------------------------------------------------- */
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.alert[data-autohide]').forEach(el => {
    setTimeout(() => {
      el.style.transition = 'opacity .4s';
      el.style.opacity    = '0';
      setTimeout(() => el.remove(), 400);
    }, 4000);
  });
});

/* ----------------------------------------------------------------
   Confirm dangerous actions
   ---------------------------------------------------------------- */
document.addEventListener('click', e => {
  const btn = e.target.closest('[data-confirm]');
  if (btn) {
    if (!confirm(btn.dataset.confirm)) e.preventDefault();
  }
});

// Loan reschedule button: redirect to reschedule page (if implemented)
document.addEventListener('click', e => {
  const btn = e.target.closest('#loan-reschedule-btn');
  if (!btn) return;
  e.preventDefault();
  const url = btn.dataset.rescheduleUrl;
  if (!url) return;
  if (!confirm('Open reschedule page for this loan?')) return;
  window.location = url;
});

/* ----------------------------------------------------------------
   Loan product selector — update limits hint
   ---------------------------------------------------------------- */
function onProductChange(selectEl) {
  const option = selectEl.options[selectEl.selectedIndex];
  const hint   = document.getElementById('product-hint');
  if (!hint || !option.value) return;
  const min  = option.dataset.min  || '';
  const max  = option.dataset.max  || '';
  const rate = option.dataset.rate || '';
  const method = option.dataset.method || '';
  hint.textContent = min
    ? `Amount: UGX ${Number(min).toLocaleString()} – ${Number(max).toLocaleString()} | Rate: ${rate}%/month (${method})`
    : '';
}

/* ----------------------------------------------------------------
   Format UGX amounts in input fields
   ---------------------------------------------------------------- */
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('input[data-ugx]').forEach(input => {
    input.addEventListener('blur', () => {
      const val = parseFloat(input.value.replace(/,/g, ''));
      if (!isNaN(val)) input.value = val.toLocaleString('en-UG', { maximumFractionDigits: 0 });
    });
    input.addEventListener('focus', () => {
      input.value = input.value.replace(/,/g, '');
    });
  });
});

/* ----------------------------------------------------------------
   HTMX: trigger schedule preview on field change
   ---------------------------------------------------------------- */
function triggerSchedulePreview() {
  const form    = document.getElementById('loan-params-form');
  const preview = document.getElementById('schedule-preview');
  if (!form || !preview) return;

  const params = new URLSearchParams(new FormData(form));
  const url    = preview.dataset.url + '?' + params.toString();

  preview.innerHTML = '<div style="padding:20px;text-align:center"><span class="spinner"></span></div>';

  fetch(url, { headers: { 'HX-Request': 'true' } })
    .then(r => r.text())
    .then(html => { preview.innerHTML = html; });
}

/* ----------------------------------------------------------------
   CEO Dashboard — Monthly collection chart
   ---------------------------------------------------------------- */
function initCollectionChart(labels, collected, interest) {
  const ctx = document.getElementById('collection-chart');
  if (!ctx || typeof Chart === 'undefined') return;

  const existing = Chart.getChart(ctx);
  if (existing) existing.destroy();

  new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [
        {
          label:           'Total Collected',
          data:            collected,
          backgroundColor: 'rgba(45,212,191,.25)',
          borderColor:     '#2dd4bf',
          borderWidth:     1.5,
          borderRadius:    4,
        },
        {
          label:           'Interest Income',
          data:            interest,
          backgroundColor: 'rgba(251,191,36,.2)',
          borderColor:     '#fbbf24',
          borderWidth:     1.5,
          borderRadius:    4,
        },
      ],
    },
    options: {
      responsive:         true,
      maintainAspectRatio: false,
      plugins: {
        legend: { labels: { color: '#8b949e', font: { family: 'DM Sans', size: 12 } } },
        tooltip: {
          backgroundColor: '#161b22',
          borderColor:     '#30363d',
          borderWidth:     1,
          titleColor:      '#e6edf3',
          bodyColor:       '#8b949e',
          callbacks: {
            label: ctx => ` UGX ${Number(ctx.parsed.y).toLocaleString('en-UG', { maximumFractionDigits: 0 })}`,
          },
        },
      },
      scales: {
        x: { ticks: { color: '#8b949e' }, grid: { color: '#21273a' } },
        y: {
          ticks: {
            color: '#8b949e',
            callback: v => 'UGX ' + Number(v).toLocaleString('en-UG', { notation: 'compact', maximumFractionDigits: 1 }),
          },
          grid: { color: '#21273a' },
        },
      },
    },
  });
}

function initCollectionTrendChart(labels, collected, interest) {
  const ctx = document.getElementById('collection-trend-chart');
  if (!ctx || typeof Chart === 'undefined') return;

  const existing = Chart.getChart(ctx);
  if (existing) existing.destroy();

  const totalCashIn = collected.map((value, idx) => Number(value) + Number(interest[idx] || 0));

  new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label: 'Cash In',
          data: totalCashIn,
          borderColor: '#2dd4bf',
          backgroundColor: 'rgba(45,212,191,.16)',
          tension: 0.35,
          fill: true,
          pointRadius: 3,
          pointHoverRadius: 4,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { labels: { color: '#8b949e', font: { family: 'DM Sans', size: 12 } } },
        tooltip: {
          backgroundColor: '#161b22',
          borderColor: '#30363d',
          borderWidth: 1,
          titleColor: '#e6edf3',
          bodyColor: '#8b949e',
          callbacks: {
            label: ctx => ` UGX ${Number(ctx.parsed.y).toLocaleString('en-UG', { maximumFractionDigits: 0 })}`,
          },
        },
      },
      scales: {
        x: { ticks: { color: '#8b949e' }, grid: { color: '#21273a' } },
        y: {
          ticks: {
            color: '#8b949e',
            callback: v => 'UGX ' + Number(v).toLocaleString('en-UG', { notation: 'compact', maximumFractionDigits: 1 }),
          },
          grid: { color: '#21273a' },
        },
      },
    },
  });
}

function initRiskChart(riskData) {
  const ctx = document.getElementById('risk-chart');
  if (!ctx || typeof Chart === 'undefined') return;

  const existing = Chart.getChart(ctx);
  if (existing) existing.destroy();

  const labels = ['Low Risk', 'Normal', 'Watch', 'Substandard', 'Doubtful', 'Loss'];
  const data = [riskData.LOW || 0, riskData.NORMAL || 0, riskData.WATCH || 0, riskData.SUBSTANDARD || 0, riskData.DOUBTFUL || 0, riskData.LOSS || 0];
  const colors = ['#4ade80', '#2dd4bf', '#fbbf24', '#ff9f1c', '#f87171', '#8b0000'];
  const bgColors = colors.map(c => c + '40'); // Add transparency

  new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels,
      datasets: [
        {
          data: data,
          backgroundColor: bgColors,
          borderColor: colors,
          borderWidth: 2,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: 'bottom',
          labels: { color: '#8b949e', font: { family: 'DM Sans', size: 12 }, padding: 12 },
        },
        tooltip: {
          backgroundColor: '#161b22',
          borderColor: '#30363d',
          borderWidth: 1,
          titleColor: '#e6edf3',
          bodyColor: '#8b949e',
          callbacks: {
            label: ctx => {
              const value = ctx.parsed || 0;
              const total = data.reduce((a, b) => a + b, 0) || 1;
              const pct = ((value / total) * 100).toFixed(1);
              return ` ${value} loan(s) (${pct}%)`;
            },
          },
        },
      },
    },
  });
}

function initExpenseTrendChart(labels, values) {
  const ctx = document.getElementById('expense-trend-chart');
  if (!ctx || typeof Chart === 'undefined') return;

  const existing = Chart.getChart(ctx);
  if (existing) existing.destroy();

  new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label: 'Operating Expenses',
          data: values,
          borderColor: '#f59e0b',
          backgroundColor: 'rgba(245,158,11,.16)',
          tension: 0.35,
          fill: true,
          pointRadius: 3,
          pointHoverRadius: 4,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { labels: { color: '#8b949e', font: { family: 'DM Sans', size: 12 } } },
        tooltip: {
          backgroundColor: '#161b22',
          borderColor: '#30363d',
          borderWidth: 1,
          titleColor: '#e6edf3',
          bodyColor: '#8b949e',
          callbacks: {
            label: ctx => ` UGX ${Number(ctx.parsed.y).toLocaleString('en-UG', { maximumFractionDigits: 0 })}`,
          },
        },
      },
      scales: {
        x: { ticks: { color: '#8b949e' }, grid: { color: '#21273a' } },
        y: {
          ticks: {
            color: '#8b949e',
            callback: v => 'UGX ' + Number(v).toLocaleString('en-UG', { notation: 'compact', maximumFractionDigits: 1 }),
          },
          grid: { color: '#21273a' },
        },
      },
    },
  });
}

function initExpenseChart(expenseData) {
  const ctx = document.getElementById('expense-chart');
  if (!ctx || typeof Chart === 'undefined') return;

  const existing = Chart.getChart(ctx);
  if (existing) existing.destroy();

  const labels = expenseData.map(item => item.label);
  const values = expenseData.map(item => item.value);
  const colors = ['#4ade80', '#fbbf24', '#f87171', '#8b5cf6', '#38bdf8'];
  const bgColors = colors.slice(0, labels.length).map(c => c + '40');

  new Chart(ctx, {
    type: 'pie',
    data: {
      labels,
      datasets: [
        {
          data: values,
          backgroundColor: bgColors,
          borderColor: colors.slice(0, labels.length),
          borderWidth: 2,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: 'bottom',
          labels: { color: '#8b949e', font: { family: 'DM Sans', size: 12 }, padding: 12 },
        },
        tooltip: {
          backgroundColor: '#161b22',
          borderColor: '#30363d',
          borderWidth: 1,
          titleColor: '#e6edf3',
          bodyColor: '#8b949e',
          callbacks: {
            label: ctx => {
              const value = Number(ctx.parsed).toLocaleString('en-UG', { maximumFractionDigits: 0 });
              return ` ${ctx.label}: UGX ${value}`;
            },
          },
        },
      },
    },
  });
}

/* ================================================================
   Select2: Searchable Dropdowns
   ================================================================ */
document.addEventListener('DOMContentLoaded', () => {
  if (typeof $ === 'undefined' && typeof jQuery === 'undefined') {
    // Select2 requires jQuery; create a lightweight wrapper
    if (typeof jQuery !== 'undefined') {
      jQuery('select').select2({
        width: '100%',
        allowClear: true,
        minimumInputLength: 0,
      });
    }
    return;
  }
  
  // Initialize Select2 on all select elements
    if (window.jQuery) {
    // Initialize Select2 on selects that are not already initialized by page-specific scripts.
    window.jQuery('select').each(function(){
      try {
        var $el = window.jQuery(this);
        if ($el.hasClass('select2-hidden-accessible')) return; // already initialized
        $el.select2({
          width: '100%',
          allowClear: false,
          minimumInputLength: 0,
          placeholder: 'Search...',
          containerCssClass: 'form-control',
        });
      } catch(e) {
        console.warn('Select2 init skipped for element', this, e);
      }
    });
    // Special: loan selector should use AJAX to avoid loading all loans
      try {
        if (window.jQuery('#loan_id').length && !window.jQuery('#loan_id').hasClass('select2-hidden-accessible')) {
          window.jQuery('#loan_id').select2({
            width: '100%',
            ajax: {
              url: '/loans/search/',
              dataType: 'json',
              delay: 250,
              data: function(params) { return { q: params.term }; },
              processResults: function(data) { return { results: data.results }; },
            },
            minimumInputLength: 1,
            placeholder: 'Search loan by number or client name',
          });
        }
      } catch (e) {
        console.warn('Select2 loan AJAX init failed', e);
      }
  }
});

/* ================================================================
   Dashboard Cards: Make clickable/pressable
   ================================================================ */
document.addEventListener('DOMContentLoaded', () => {
  // Make metric cards clickable if they link to another page
  document.querySelectorAll('[data-link]').forEach(card => {
    card.classList.add('clickable-card');
    card.addEventListener('click', () => {
      const url = card.dataset.link;
      if (url) window.location.href = url;
    });
  });

  // Make table rows with data-link clickable
  document.querySelectorAll('tbody tr[data-link]').forEach(row => {
    row.classList.add('clickable-row');
    row.addEventListener('click', (e) => {
      // Don't navigate if clicking on buttons or links
      if (e.target.closest('a, button, .btn')) return;
      const url = row.dataset.link;
      if (url) window.location.href = url;
    });
  });
});

/* ================================================================
   MODAL SYSTEM
   ================================================================ */

// Create modal overlay element if it doesn't exist
function getModalOverlay() {
  let overlay = document.getElementById('modal-overlay');
  if (!overlay) {
    overlay = document.createElement('div');
    overlay.id = 'modal-overlay';
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `
      <div class="modal" role="dialog" aria-modal="true">
        <div class="modal-header">
          <h3 class="modal-title"></h3>
          <button class="modal-close" aria-label="Close modal">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </div>
        <div class="modal-body"></div>
        <div class="modal-footer"></div>
      </div>
    `;
    document.body.appendChild(overlay);

    // Close on overlay click
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) Modal.close();
    });

    // Close on Escape key
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && overlay.classList.contains('active')) {
        Modal.close();
      }
    });

    // Close button
    overlay.querySelector('.modal-close').addEventListener('click', Modal.close);
  }
  return overlay;
}

const Modal = {
  _overlay: null,
  _onClose: null,

  get overlay() {
    if (!this._overlay) this._overlay = getModalOverlay();
    return this._overlay;
  },

  open(options = {}) {
    const {
      title = '',
      body = '',
      footer = '',
      size = 'default', // 'small', 'default', 'large'
      onClose = null
    } = options;

    this._onClose = onClose;

    const overlay = this.overlay;
    const modal = overlay.querySelector('.modal');
    const titleEl = overlay.querySelector('.modal-title');
    const bodyEl = overlay.querySelector('.modal-body');
    const footerEl = overlay.querySelector('.modal-footer');

    // Set content
    titleEl.textContent = title;
    bodyEl.innerHTML = body;
    footerEl.innerHTML = footer;

    // Set size
    const sizes = { small: '400px', default: '560px', large: '720px' };
    modal.style.maxWidth = sizes[size] || sizes.default;

    // Show
    overlay.classList.add('active');
    document.body.style.overflow = 'hidden';

    // Focus first focusable element
    setTimeout(() => {
      const firstFocusable = bodyEl.querySelector('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
      if (firstFocusable) firstFocusable.focus();
    }, 100);

    return this;
  },

  close() {
    const overlay = this._overlay;
    if (!overlay) return;

    overlay.classList.remove('active');
    document.body.style.overflow = '';

    if (this._onClose) {
      this._onClose();
      this._onClose = null;
    }
  },

  confirm(options = {}) {
    const {
      title = 'Confirm',
      message = 'Are you sure?',
      confirmText = 'Confirm',
      cancelText = 'Cancel',
      confirmClass = 'btn-primary',
      onConfirm = null,
      onCancel = null
    } = options;

    const body = `<p style="font-size:14px;line-height:1.6;color:var(--text-secondary);margin:0;">${message}</p>`;
    const footer = `
      <button class="btn btn-secondary" id="modal-cancel-btn">${cancelText}</button>
      <button class="btn ${confirmClass}" id="modal-confirm-btn">${confirmText}</button>
    `;

    this.open({ title, body, footer });

    // Handle confirm
    document.getElementById('modal-confirm-btn').addEventListener('click', () => {
      this.close();
      if (onConfirm) onConfirm();
    });

    document.getElementById('modal-cancel-btn').addEventListener('click', () => {
      this.close();
      if (onCancel) onCancel();
    });

    return this;
  },

  alert(options = {}) {
    const {
      title = 'Message',
      message = '',
      okText = 'OK',
      type = 'info', // 'info', 'success', 'warning', 'error'
      onOk = null
    } = options;

    const icons = {
      info: '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
      success: '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>',
      warning: '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
      error: '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>'
    };

    const colors = {
      info: 'var(--info)',
      success: 'var(--success)',
      warning: 'var(--warning)',
      error: 'var(--danger)'
    };

    const body = `
      <div style="display:flex;align-items:flex-start;gap:16px;">
        <div style="color:${colors[type]};flex-shrink:0;">${icons[type]}</div>
        <p style="font-size:14px;line-height:1.6;color:var(--text-secondary);margin:0;flex:1;">${message}</p>
      </div>
    `;
    const footer = `<button class="btn ${type === 'error' ? 'btn-danger' : 'btn-primary'}" id="modal-ok-btn">${okText}</button>`;

    this.open({ title, body, footer, size: 'small' });

    document.getElementById('modal-ok-btn').addEventListener('click', () => {
      this.close();
      if (onOk) onOk();
    });

    return this;
  }
};

// Make Modal globally available
window.Modal = Modal;

/* ================================================================
   TOOLTIP SYSTEM
   ================================================================ */
document.addEventListener('DOMContentLoaded', () => {
  // Initialize tooltips for elements with data-tooltip attribute
  document.querySelectorAll('[data-tooltip]').forEach(el => {
    el.addEventListener('mouseenter', showTooltip);
    el.addEventListener('mouseleave', hideTooltip);
  });
});

function showTooltip(e) {
  const el = e.currentTarget;
  const text = el.getAttribute('data-tooltip');
  if (!text) return;

  let tooltip = el.querySelector('.tooltip-bubble');
  if (!tooltip) {
    tooltip = document.createElement('div');
    tooltip.className = 'tooltip-bubble';
    tooltip.style.cssText = `
      position: absolute;
      bottom: 100%;
      left: 50%;
      transform: translateX(-50%);
      padding: 6px 10px;
      background: var(--text-primary);
      color: var(--bg-surface);
      font-size: 12px;
      font-weight: 500;
      border-radius: var(--radius-sm);
      white-space: nowrap;
      pointer-events: none;
      z-index: 1000;
      margin-bottom: 8px;
      opacity: 0;
      transition: opacity 0.15s ease, transform 0.15s ease;
    `;
    tooltip.textContent = text;
    el.style.position = 'relative';
    el.appendChild(tooltip);
  }

  setTimeout(() => {
    tooltip.style.opacity = '1';
    tooltip.style.transform = 'translateX(-50%) translateY(-4px)';
  }, 10);
}

function hideTooltip(e) {
  const tooltip = e.currentTarget.querySelector('.tooltip-bubble');
  if (tooltip) {
    tooltip.style.opacity = '0';
    tooltip.style.transform = 'translateX(-50%) translateY(0)';
    setTimeout(() => tooltip.remove(), 150);
  }
}

/* ================================================================
   FILTER BAR SCROLL INDICATOR
   ================================================================ */
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.filter-bar-single-row').forEach(bar => {
    bar.classList.add('filter-scroll-indicator');
    
    const checkScroll = () => {
      const canScrollRight = bar.scrollWidth > bar.clientWidth + bar.scrollLeft + 10;
      bar.classList.toggle('can-scroll-right', canScrollRight);
    };

    bar.addEventListener('scroll', checkScroll);
    window.addEventListener('resize', checkScroll);
    checkScroll();
  });
});
