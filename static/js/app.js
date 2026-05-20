/* ─────────────────────────────────────────────────────────────────────────────
   Email Agent — Alpine.js Stores & Shared Utilities
   app.js is loaded with `defer` BEFORE Alpine in <head> so the alpine:init
   listener is always registered before Alpine fires it, even when cached.
   ───────────────────────────────────────────────────────────────────────────── */

document.addEventListener('alpine:init', () => {

  /* ── agentStore ──────────────────────────────────────────────────────────── */
  Alpine.store('agent', {
    // Reactive state
    running:       false,
    logs:          [],
    draftCount:    0,
    reviewCount:   0,
    error:         null,
    isReconnecting: false,
    toggling:      false,   // true while toggle API call is in-flight

    // Computed: plain functions so Alpine reactive proxy tracks them reliably
    get isAuthError() {
      return Boolean(this.error && /auth|token|credential|expired/i.test(this.error));
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

    // Lifecycle — Alpine auto-calls init() when the store is registered
    init() {
      this.refresh();
      setInterval(() => this.refresh(), 5000);
    },

    async refresh() {
      if (this.isReconnecting) return;
      try {
        const res = await fetch('/api/status');
        if (!res.ok) return;
        const data = await res.json();
        this.running     = data.running    ?? false;
        this.logs        = data.logs       ?? [];
        this.draftCount  = data.draft_count ?? 0;
        this.reviewCount = data.review_count ?? 0;
        this.error       = data.error      ?? null;
      } catch (_) {
        // Server unreachable — stay silent, retry on next interval
      }
    },

    async toggle() {
      if (this.toggling) return;
      this.toggling = true;
      this.error = null;

      const endpoint = this.running ? '/api/agent/stop' : '/api/agent/start';
      try {
        const res = await fetch(endpoint, { method: 'POST' });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
      } catch (e) {
        showToast('Request failed: ' + e.message, 'error');
        this.toggling = false;
        return;
      }

      // Poll three times at short intervals so errors surface quickly.
      // toggling is ALWAYS released at the end — no complex exit conditions.
      const sleep = ms => new Promise(r => setTimeout(r, ms));
      await sleep(600);  await this.refresh();
      await sleep(600);  await this.refresh();
      await sleep(800);  await this.refresh();
      this.toggling = false;
    },

    async reconnect() {
      this.isReconnecting = true;
      this.error = null;
      try {
        await fetch('/api/agent/reconnect', { method: 'POST' });
        this._pollOAuth();
      } catch (e) {
        this.isReconnecting = false;
        showToast('Reconnect request failed. Try again.', 'error');
      }
    },

    _pollOAuth() {
      const t = setInterval(async () => {
        try {
          const res  = await fetch('/setup/api/oauth_status');
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
  });

  /* ── reviewStore ─────────────────────────────────────────────────────────── */
  Alpine.store('review', {
    count: 0,

    init() {
      this.refresh();
      setInterval(() => this.refresh(), 8000);
    },

    async refresh() {
      try {
        const res  = await fetch('/api/review/count');
        if (!res.ok) return;
        const data = await res.json();
        this.count = data.count ?? 0;
      } catch (_) {}
    },
  });

});

/* ── showToast ───────────────────────────────────────────────────────────────
   Global toast notification. Can be called from anywhere including Alpine
   event handlers and Jinja templates.
   ─────────────────────────────────────────────────────────────────────────── */
function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container')
    || (() => {
      const el = document.createElement('div');
      el.id = 'toast-container';
      el.className = 'toast-container';
      document.body.appendChild(el);
      return el;
    })();

  const icons = {
    success: `<svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/></svg>`,
    error:   `<svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/></svg>`,
    info:    `<svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path stroke-linecap="round" d="M12 8v4m0 4h.01"/></svg>`,
  };

  const toast = document.createElement('div');
  toast.className = `toast toast--${type}`;
  toast.innerHTML = (icons[type] || icons.info) + `<span>${message}</span>`;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.transition = 'opacity 200ms ease, transform 200ms ease';
    toast.style.opacity    = '0';
    toast.style.transform  = 'translateX(8px)';
    setTimeout(() => toast.remove(), 220);
  }, 3800);
}

/* ── captureEditableBody ─────────────────────────────────────────────────────
   Copies innerHTML of a contenteditable div into a hidden form input before
   the review form submits.
   ─────────────────────────────────────────────────────────────────────────── */
function captureEditableBody(form, itemId) {
  const editable = document.getElementById('body-' + itemId);
  const hidden   = form.querySelector('input[name="body_html"]');
  if (editable && hidden) hidden.value = editable.innerHTML;
}

/* ── Social link builder (setup/settings) ───────────────────────────────────── */
function addSocialLink(label = '', urlPrefix = '') {
  const container = document.getElementById('links-container');
  if (!container) return;
  const idx = container.querySelectorAll('.link-row').length;
  const row = document.createElement('div');
  row.className = 'link-row';
  row.style.cssText = 'display:flex;gap:8px;align-items:center;';
  row.innerHTML = `
    <input type="text"  name="social_label_${idx}" value="${label}"
      placeholder="Label" class="input" style="width:120px;">
    <input type="url"   name="social_url_${idx}"   value="${urlPrefix}"
      placeholder="https://…" class="input" style="flex:1;">
    <button type="button" onclick="removeSocialLink(this)"
      style="color:var(--text-tertiary);font-size:20px;line-height:1;background:none;
             border:none;cursor:pointer;padding:0 4px;" aria-label="Remove">×</button>`;
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
    const lbl = row.querySelector('input[name^="social_label"]');
    const url = row.querySelector('input[name^="social_url"]');
    if (lbl) lbl.name = `social_label_${i}`;
    if (url) url.name = `social_url_${i}`;
  });
}
