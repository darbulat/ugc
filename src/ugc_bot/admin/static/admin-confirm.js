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


document.querySelectorAll("[data-order-close]").forEach((button) => {
  const dialog = button.form.querySelector("dialog");
  button.addEventListener("click", () => dialog.showModal());
  dialog.querySelector("[data-order-close-cancel]").addEventListener("click", () => dialog.close());
});


const orderFilterMenu = document.querySelector(".order-worklist-more");
if (orderFilterMenu) {
  document.addEventListener("click", (event) => {
    if (!orderFilterMenu.contains(event.target)) orderFilterMenu.open = false;
  });
  orderFilterMenu.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && orderFilterMenu.open) {
      orderFilterMenu.open = false;
      orderFilterMenu.querySelector("summary").focus();
    }
  });
}
