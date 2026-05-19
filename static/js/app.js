// Global utility: show a temporary toast without a page reload
function showToast(message, type) {
  const container = document.getElementById('toast-container') ||
    (() => {
      const el = document.createElement('div');
      el.id = 'toast-container';
      el.className = 'fixed top-4 right-4 z-50 space-y-2';
      document.body.appendChild(el);
      return el;
    })();

  const toast = document.createElement('div');
  toast.className = `toast toast-${type} flex items-center gap-2 px-4 py-3 rounded-lg shadow-lg text-sm font-medium`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 4000);
}
