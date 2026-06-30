document.addEventListener("submit", (event) => {
  const form = event.target.closest("form[data-confirm]");
  if (!form) {
    return;
  }

  const message = form.dataset.confirm;
  if (message && !window.confirm(message)) {
    event.preventDefault();
  }
});
