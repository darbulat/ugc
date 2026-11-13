const editor = document.querySelector("#order-edit-form");

for (const counter of editor.querySelectorAll("[data-character-limit]")) {
  const field = document.getElementById(counter.dataset.field);
  const limit = Number(counter.dataset.characterLimit);
  const saved = field.value;
  const update = () => {
    const length = Array.from(field.value).length;
    const exceeded = length > limit;
    counter.textContent = exceeded
      ? `${length} / ${limit} · превышение на ${length - limit}`
      : `${length} / ${limit}`;
    counter.classList.toggle("text-danger", exceeded);
    field.setCustomValidity(exceeded && field.value !== saved
      ? `Максимум ${limit} символов.`
      : "");
  };
  field.addEventListener("input", update);
  update();
}

const audience = document.getElementById("order-edit-audience");
const watched = [...audience.querySelectorAll("input, select, textarea"),
  editor.elements.namedItem("order_type"), editor.elements.namedItem("price")];
const savedAudience = watched.map(readValue);
const countHint = document.getElementById("order-audience-dirty");
for (const field of watched) {
  field.addEventListener("input", () => {
    countHint.hidden = !watched.some((item, index) => readValue(item) !== savedAudience[index]);
  });
}

function readValue(field) {
  return field.type === "checkbox" ? field.checked : field.value;
}

  document.getElementById('order-photo-upload-button')?.addEventListener('click', async () => {
    const picker = document.getElementById('order-photo-upload');
    const status = document.getElementById('order-photo-upload-status');
    const button = document.getElementById('order-photo-upload-button');
    if (!picker.files.length) { status.textContent = 'Сначала выберите изображение.'; return; }
    const data = new FormData(); data.append('photo', picker.files[0]);
    button.disabled = true; status.textContent = 'Загружаю в Telegram…';
    try {
      const response = await fetch('/admin/order-photo-upload', {method: 'POST', body: data, credentials: 'same-origin'});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Не удалось загрузить фото');
      const field = document.querySelector('[name="product_photo_file_id"]');
      if (!field) throw new Error('Не найдено поле Telegram file_id');
      field.value = result.file_id;
      status.textContent = 'Готово. Сохраните заказ, чтобы применить картинку.';
    } catch (error) { status.textContent = error.message; }
    finally { button.disabled = false; }
  });
