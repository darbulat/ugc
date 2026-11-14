document.querySelectorAll("[data-admin-confirm]").forEach((button) => {
  button.addEventListener("click", () => {
    if (window.confirm(button.dataset.adminConfirm)) {
      button.form.requestSubmit();
    }
  });
});

document.querySelectorAll("[data-admin-manager-confirm]").forEach((form) => {
  form.addEventListener("submit", (event) => {
    const { previous_manager: previous, manager_telegram: target, confirmed } = form.elements;
    const manager = previous.dataset.managerName || previous.selectedOptions[0].text;
    const handle = `@${target.value.trim().replace(/^@+/, "")}`;
    if (window.confirm(`Заменить менеджера «${manager}» на ${handle}?`)) {
      confirmed.value = "1";
    } else {
      event.preventDefault();
    }
  });
});
