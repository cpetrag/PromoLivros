const buttons = document.querySelectorAll("[data-filter]");
const input = document.querySelector("#busca");
const count = document.querySelector("#count");

function apply() {
  const active = document.querySelector("[data-filter][aria-pressed='true']");
  const filtro = active ? active.dataset.filter : "todos";
  const query = input.value.trim().toLocaleLowerCase("pt-BR");
  let visible = 0;
  document.querySelectorAll("[data-book]").forEach((book) => {
    const discount = Number(book.dataset.discount);
    const rating = Number(book.dataset.rating);
    const haystack = book.dataset.search || "";
    let show = true;
    if (filtro === "desconto30" && discount < 30) show = false;
    if (filtro === "nota48" && rating < 4.8) show = false;
    if (query && !haystack.includes(query)) show = false;
    book.hidden = !show;
    if (show) visible += 1;
  });
  count.textContent = visible + " livros nesta lista.";
}

buttons.forEach((button) => {
  button.addEventListener("click", () => {
    buttons.forEach((item) => item.setAttribute("aria-pressed", String(item === button)));
    apply();
  });
});
input.addEventListener("input", apply);
