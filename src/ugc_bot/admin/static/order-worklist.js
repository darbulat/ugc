document.querySelectorAll("[data-order-confirm]").forEach((button) => {
  button.addEventListener("click", () => {
    if (window.confirm(button.dataset.orderConfirm)) {
      button.form.requestSubmit();
    }
  });
});
