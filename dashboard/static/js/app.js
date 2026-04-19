/**
 * MCP Forge — Client-side utilities
 * Works alongside HTMX and Alpine.js
 */

// ── Log line formatter (used by SSE log stream) ────────────────────────────
function formatLogLine(data) {
  const colors = {
    debug:   'text-gray-500',
    info:    'text-blue-400',
    warning: 'text-yellow-400',
    error:   'text-red-400',
  };
  const color = colors[data.level] || 'text-gray-300';
  const time = new Date(data.created_at).toLocaleTimeString();
  return `<div class="${color} flex gap-2 font-mono text-xs">
    <span class="text-gray-600 flex-shrink-0">[${time}]</span>
    <span class="text-gray-500 flex-shrink-0">[${data.source || '?'}]</span>
    <span>${escapeHtml(data.message)}</span>
  </div>`;
}

// ── SSE message handler ────────────────────────────────────────────────────
document.body.addEventListener('htmx:sseMessage', (event) => {
  const { type, data } = event.detail;
  if (!data) return;

  try {
    const parsed = JSON.parse(data);

    if (type === 'log') {
      // Append to any open log panel
      const panels = document.querySelectorAll('.log-panel');
      panels.forEach(panel => {
        panel.insertAdjacentHTML('beforeend', formatLogLine(parsed));
        panel.scrollTop = panel.scrollHeight;
        // Keep max 500 lines
        const lines = panel.querySelectorAll('div');
        if (lines.length > 500) lines[0].remove();
      });
    }

    if (type === 'notification') {
      // Show toast for new notifications
      showToast({ type: parsed.type || 'info', message: `${parsed.title}: ${parsed.message}` });
      // Update notification badge (dispatch to Alpine)
      window.dispatchEvent(new CustomEvent('new-notification', { detail: parsed }));
    }
  } catch (e) {
    // Not JSON — treat as plain text log
    const panels = document.querySelectorAll('.log-panel');
    panels.forEach(panel => {
      panel.insertAdjacentHTML('beforeend', `<div class="text-gray-400 text-xs font-mono">${escapeHtml(data)}</div>`);
    });
  }
});

// ── Code syntax re-highlight after HTMX swaps ─────────────────────────────
document.body.addEventListener('htmx:afterSettle', () => {
  if (typeof hljs !== 'undefined') {
    document.querySelectorAll('pre code:not(.hljs)').forEach(el => hljs.highlightElement(el));
  }
});

// ── Escape HTML helper ─────────────────────────────────────────────────────
function escapeHtml(str) {
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}

// ── Keyboard shortcut: Cmd/Ctrl+K → focus chat input ─────────────────────
document.addEventListener('keydown', (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
    e.preventDefault();
    const chatInput = document.getElementById('chat-input');
    if (chatInput) chatInput.focus();
  }
});

// ── Auto-scroll chat to bottom on load ────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  const chatMessages = document.getElementById('chat-messages');
  if (chatMessages) chatMessages.scrollTop = chatMessages.scrollHeight;
});
