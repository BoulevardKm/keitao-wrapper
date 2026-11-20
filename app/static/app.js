document.querySelectorAll("[data-confirm]").forEach((form) => {
  form.addEventListener("submit", (event) => {
    if (!window.confirm(form.dataset.confirm)) {
      event.preventDefault();
    }
  });
});

document.querySelectorAll("[data-finder]").forEach((finder) => {
  const input = finder.querySelector(".finder-input");
  const hidden = finder.querySelector(".finder-id");
  const menu = finder.querySelector(".finder-menu");
  let timer = 0;

  const close = () => {
    menu.hidden = true;
    menu.innerHTML = "";
  };

  const showError = (text) => {
    close();
    finder.querySelector(".finder-error")?.remove();
    const note = document.createElement("p");
    note.className = "finder-error";
    note.textContent = text;
    finder.append(note);
  };

  input.addEventListener("input", () => {
    hidden.value = /^\d+$/.test(input.value.trim()) ? input.value.trim() : "";
    window.clearTimeout(timer);
    const query = input.value.trim();
    if (query.length < 1) {
      close();
      finder.querySelector(".finder-error")?.remove();
      return;
    }
    timer = window.setTimeout(async () => {
      const response = await fetch("/api/offers?q=" + encodeURIComponent(query));
      const payload = await response.json();
      menu.innerHTML = "";
      finder.querySelector(".finder-error")?.remove();
      if (!response.ok) {
        showError(payload.error || "Не удалось получить офферы");
        return;
      }
      payload.forEach((offer) => {
        const item = document.createElement("button");
        item.type = "button";
        item.textContent = offer.id + " — " + offer.name;
        item.addEventListener("click", () => {
          hidden.value = String(offer.id);
          input.value = offer.id + " — " + offer.name;
          close();
        });
        menu.append(item);
      });
      menu.hidden = payload.length === 0;
    }, 200);
  });

  finder.closest("form").addEventListener("submit", () => {
    if (!hidden.value && /^\d+$/.test(input.value.trim())) {
      hidden.value = input.value.trim();
    }
  });

  document.addEventListener("click", (event) => {
    if (!finder.contains(event.target)) {
      close();
    }
  });
});
