function showCopyFeedback(message) {
  document.querySelector('.copy-feedback')?.remove();
  const feedback = document.createElement('div');
  feedback.className = 'copy-feedback';
  feedback.textContent = message;
  document.body.appendChild(feedback);
  window.setTimeout(() => feedback.remove(), 1800);
}

async function copyText(value, message) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
  } else {
    const helper = document.createElement('textarea');
    helper.value = value;
    helper.style.position = 'fixed';
    helper.style.opacity = '0';
    document.body.appendChild(helper);
    helper.select();
    document.execCommand('copy');
    helper.remove();
  }
  showCopyFeedback(message);
}

document.addEventListener('click', async (event) => {
  const commandButton = event.target.closest('[data-copy-command]');
  if (commandButton) {
    await copyText(commandButton.dataset.copyCommand, 'Comando copiado.');
    return;
  }
  const copyButton = event.target.closest('[data-email][data-password]');
  if (!copyButton) return;
  const credentials = `${copyButton.dataset.email}\n${copyButton.dataset.password}`;
  await copyText(credentials, 'Conta copiada. Cole no campo de e-mail.');
});
