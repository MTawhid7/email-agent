/* ─────────────────────────────────────────────────────────────────────────────
   Email Agent — Alpine.js Stores & Shared Utilities
   ───────────────────────────────────────────────────────────────────────────── */

document.addEventListener('alpine:init', () => {

  /* ── agentStore: dashboard status, log, reconnect ── */
  Alpine.store('agent', {
    running: false,
    logs: [],
    draftCount: 0,
    reviewCount: 0,
    error: null,
    isReconnecting: false,
    lastLogCount: 0,
    _pollTimer: null,

    init() {
      this.refresh();
      this._pollTimer = setInterval(() => this.refresh(), 5000);
    },

    async refresh() {
      if (this.isReconnecting) return;
      try {
        const res = await fetch('/api/status');
        if (!res.ok) return;
        const data = await res.json();
        this.running    = data.running;
        this.logs       = data.logs ?? [];
        this.draftCount = data.draft_count ?? 0;
        this.reviewCount = data.review_count ?? 0;
        this.error      = data.error ?? null;
      } catch (_) { /* network unavailable — stay silent */ }
    },

    async toggle() {
      const endpoint = this.running ? '/api/agent/stop' : '/api/agent/start';
      await fetch(endpoint, { method: 'POST' });
      await this.refresh();
    },

    async reconnect() {
      this.isReconnecting = true;
      this.error = null;
      try {
        await fetch('/api/agent/reconnect', { method: 'POST' });
        this._pollOAuth();
      } catch (e) {
        this.isReconnecting = false;
        showToast('Reconnect failed. Try again.', 'error');
      }
    },

    _pollOAuth() {
      const t = setInterval(async () => {
        try {
          const res = await fetch('/setup/api/oauth_status');
          const data = await res.json();
          if (data.done) {
            clearInterval(t);
            this.isReconnecting = false;
            await fetch('/api/agent/start', { method: 'POST' });
            await this.refresh();
            showToast('Gmail reconnected. Agent restarted.', 'success');
          } else if (data.error) {
            clearInterval(t);
            this.isReconnecting = false;
            showToast('OAuth failed: ' + data.error, 'error');
          }
        } catch (_) { /* retry next tick */ }
      }, 2000);
    },

    get isAuthError() {
      return this.error && /auth|token|credential|expired/i.test(this.error);
    },

    get statusLabel() {
      if (this.isReconnecting) return 'Reconnecting…';
      if (this.isAuthError)    return 'Gmail disconnected';
      return this.running ? 'Running' : 'Stopped';
    },

    get statusDotClass() {
      if (this.isReconnecting) return 'status-dot--warning';
      if (this.isAuthError)    return 'status-dot--error';
      return this.running ? 'status-dot--running' : 'status-dot--stopped';
    },
  });

  /* ── reviewStore: sidebar badge count ── */
  Alpine.store('review', {
    count: 0,
    _timer: null,

    init() {
      this.refresh();
      this._timer = setInterval(() => this.refresh(), 8000);
    },

    async refresh() {
      try {
        const res = await fetch('/api/review/count');
        if (!res.ok) return;
        const data = await res.json();
        this.count = data.count ?? 0;
      } catch (_) {}
    },
  });

});

/* ── showToast: global toast notification ── */
function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container')
    || (() => {
      const el = document.createElement('div');
      el.id = 'toast-container';
      el.className = 'toast-container';
      document.body.appendChild(el);
      return el;
    })();

  const toast = document.createElement('div');
  const iconMap = {
    success: `<svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/></svg>`,
    error:   `<svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/></svg>`,
    info:    `<svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>`,
  };
  toast.className = `toast toast--${type}`;
  toast.innerHTML = (iconMap[type] || iconMap.info) + `<span>${message}</span>`;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.transition = 'opacity 200ms ease, transform 200ms ease';
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(8px)';
    setTimeout(() => toast.remove(), 220);
  }, 3800);
}

/* ── captureEditableBody: capture contenteditable HTML before form submit ── */
function captureEditableBody(form, itemId, action) {
  const editable = document.getElementById('body-' + itemId);
  const hidden   = form.querySelector('input[name="body_html"]');
  if (editable && hidden) hidden.value = editable.innerHTML;
}

/* ── Social link builder for setup/settings ── */
function addSocialLink(label = '', urlPrefix = '') {
  const container = document.getElementById('links-container');
  if (!container) return;
  const idx = container.querySelectorAll('.link-row').length;
  const row = document.createElement('div');
  row.className = 'link-row flex-gap-2';
  row.style.cssText = 'display:flex;gap:8px;align-items:center;';
  row.innerHTML = `
    <input type="text" name="social_label_${idx}" value="${label}"
      placeholder="Label" class="input" style="width:120px;">
    <input type="url" name="social_url_${idx}" value="${urlPrefix}"
      placeholder="https://…" class="input" style="flex:1;">
    <button type="button" onclick="removeSocialLink(this)"
      style="color:var(--text-tertiary);font-size:20px;line-height:1;background:none;border:none;cursor:pointer;padding:0 4px;"
      aria-label="Remove">×</button>`;
  container.appendChild(row);
  row.querySelector('input[type="url"]').focus();
  renumberSocialLinks();
}

function removeSocialLink(btn) {
  btn.closest('.link-row').remove();
  renumberSocialLinks();
}

function renumberSocialLinks() {
  document.querySelectorAll('.link-row').forEach((row, i) => {
    const label = row.querySelector('input[name^="social_label"]');
    const url   = row.querySelector('input[name^="social_url"]');
    if (label) label.name = `social_label_${i}`;
    if (url)   url.name   = `social_url_${i}`;
  });
}
