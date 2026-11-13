document.querySelectorAll("[data-admin-confirm]").forEach((button) => {
  button.addEventListener("click", () => {
    if (window.confirm(button.dataset.adminConfirm)) {
      button.form.requestSubmit();
    }
  });
});
