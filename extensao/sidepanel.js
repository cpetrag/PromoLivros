let plan = { slots: [], amanha: [], previa_id: "" };

const status = document.getElementById("status");
const slots = document.getElementById("slots");
const sobras = document.getElementById("sobras");
const ordem = document.getElementById("ordem");

document.getElementById("config-open").addEventListener("click", () => {
  document.getElementById("config").hidden = false;
});

document.getElementById("config").addEventListener("submit", (event) => {
  event.preventDefault();
  chrome.runtime.sendMessage({
    type: "save-config",
    panelUrl: document.getElementById("panel-url").value,
    token: document.getElementById("token").value,
  }, () => {
    document.getElementById("config").hidden = true;
    load();
  });
});

ordem.addEventListener("change", () => {
  chrome.runtime.sendMessage({ type: "previa", ordem: ordem.value }, (payload) => {
    if (!payload || payload.error) {
      status.textContent = payload && payload.error ? payload.error : "Não recalculei.";
      return;
    }
    plan = payload;
    draw();
  });
});

document.getElementById("aplicar").addEventListener("click", () => {
  if (!plan.previa_id) {
    status.textContent = "Revise a fila de novo.";
    return;
  }
  chrome.runtime.sendMessage({ type: "aplicar", previaId: plan.previa_id }, (payload) => {
    if (!payload || payload.error) {
      status.textContent = payload && payload.error ? payload.error : "Não apliquei.";
      return;
    }
    status.textContent = payload.message || "Fila aplicada.";
    plan = payload.plan || plan;
    draw();
  });
});

document.getElementById("soltar").addEventListener("click", () => {
  chrome.runtime.sendMessage({ type: "soltar" }, (payload) => {
    if (!payload || payload.error) {
      status.textContent = payload && payload.error ? payload.error : "Não soltei.";
      return;
    }
    status.textContent = payload.count + " livros foram para o catálogo, fora da fila.";
    plan = payload.plan || { slots: [], amanha: [], previa_id: "" };
    draw();
  });
});

function load() {
  chrome.runtime.sendMessage({ type: "caixa" }, (payload) => {
    if (!payload || payload.error) {
      status.textContent = payload && payload.error ? payload.error : "Abra o token em Curadoria e cole aqui.";
      return;
    }
    status.textContent = (payload.books || []).length + " na caixa.";
    ordem.value = payload.ordem || "mine";
    plan = payload.plan || plan;
    draw();
  });
}

function draw() {
  slots.textContent = "";
  (plan.slots || []).forEach((slot) => {
    const row = document.createElement("div");
    row.className = "slot";
    const clock = document.createElement("div");
    clock.className = "clock";
    clock.textContent = slot.clock;
    const body = document.createElement("div");
    body.append(half(slot.amazon, "Amazon"), half(slot.ml, "Mercado Livre"));
    row.append(clock, body);
    slots.append(row);
  });
  const items = plan.amanha || [];
  sobras.hidden = !items.length;
  sobras.querySelector("summary").textContent = items.length + " não cabem hoje";
  const list = sobras.querySelector("ul");
  list.textContent = "";
  items.forEach((item) => {
    const li = document.createElement("li");
    li.textContent = item.title;
    list.append(li);
  });
}

function half(item, store) {
  const line = document.createElement("p");
  line.className = "half";
  if (!item) {
    line.textContent = store + " · vazio";
    return line;
  }
  line.textContent = item.title + (item.discount ? " · −" + item.discount + "%" : "");
  const up = document.createElement("button");
  up.type = "button";
  up.textContent = "↑";
  up.addEventListener("click", () => move(item.id, -1));
  const down = document.createElement("button");
  down.type = "button";
  down.textContent = "↓";
  down.addEventListener("click", () => move(item.id, 1));
  const drop = document.createElement("button");
  drop.type = "button";
  drop.textContent = "×";
  drop.addEventListener("click", () => {
    chrome.runtime.sendMessage({ type: "tirar", id: item.id, store: item.store }, (payload) => {
      if (!payload || payload.error) return;
      plan = payload.plan || plan;
      draw();
    });
  });
  line.append(up, down, drop);
  return line;
}

function move(id, passo) {
  chrome.runtime.sendMessage({ type: "ordem", id, passo }, (payload) => {
    if (!payload || payload.error) return;
    plan = payload;
    draw();
  });
}

chrome.runtime.sendMessage({ type: "config" }, (stored) => {
  if (!stored) return;
  document.getElementById("panel-url").value = stored.panelUrl || "https://painel.promolivros.org";
  document.getElementById("token").value = stored.token || "";
});

load();
