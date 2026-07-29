/**
 * ai-chat.js — EMO AI Chat component inside the Web HUD.
 * Connects the HUD chat interface to EMO's backend orchestrator.
 */
(() => {
  const input = document.getElementById('ai-input');
  const sendBtn = document.getElementById('ai-send');
  const messagesContainer = document.getElementById('ai-messages');

  if (!input || !sendBtn || !messagesContainer) return;

  function appendMessage(text, role) {
    const msg = document.createElement('div');
    msg.className = `ai-msg ${role}`;
    msg.textContent = text;
    messagesContainer.appendChild(msg);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
  }

  async function sendMessage() {
    const text = input.value.trim();
    if (!text) return;

    appendMessage(text, 'user');
    input.value = '';

    // Haptic feedback via native bridge
    if (typeof Bridge !== 'undefined') {
      Bridge.vibrate(25);
    }

    try {
      // POST wish/state to face server
      await fetch('/wish', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ wish: 'listen' })
      });

      // Poll state/history or send text to backend if chat endpoint is active
      const response = await fetch('/api/ai/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text })
      });

      if (response.ok) {
        const data = await response.json();
        appendMessage(data.reply || "Got it, Boss!", 'bot');
      } else {
        appendMessage("EMO is processing...", 'bot');
      }
    } catch (e) {
      appendMessage("Connected to edge core, waiting for response...", 'bot');
    }
  }

  sendBtn.addEventListener('click', sendMessage);
  input.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') sendMessage();
  });
})();
