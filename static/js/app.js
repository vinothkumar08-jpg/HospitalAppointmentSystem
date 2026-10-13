document.querySelectorAll("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (event) => {
        const message = form.dataset.confirm;
        if (!window.confirm(message)) {
            event.preventDefault();
        }
    });
});
