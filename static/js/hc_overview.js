const tabela = document.getElementById("tabelaHC");
const busca = document.getElementById("busca");
const mensagem = document.getElementById("mensagem");
const formNovo = document.getElementById("formNovo");
const formEditar = document.getElementById("formEditar");
const modal = document.getElementById("modalEdicao");
const fecharModal = document.getElementById("fecharModal");
const btnExportar = document.getElementById("btnExportar");
const arquivoImport = document.getElementById("arquivoImport");

let cache = [];

function showMessage(text, isError = false) {
  mensagem.textContent = text;
  mensagem.style.color = isError ? "#b91c1c" : "#0a4c78";
}

async function carregarTabela(q = "") {
  const res = await fetch(`/api/hc?q=${encodeURIComponent(q)}`);
  cache = await res.json();
  tabela.innerHTML = "";

  cache.forEach(item => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${item.nome_completo}</td>
      <td>${item.login}</td>
      <td>${item.cargo}</td>
      <td>${item.area}</td>
      <td>${item.turno}</td>
      <td><span class="badge ${item.status.toLowerCase()}">${item.status}</span></td>
      <td>${item.data_afastamento || "-"}</td>
      <td><button class="btn" onclick="abrirEdicao(${item.id})">Editar</button></td>
    `;
    tabela.appendChild(tr);
  });
}

function formToJson(form) {
  const data = new FormData(form);
  return {
    nome_completo: data.get("nome_completo"),
    login: data.get("login"),
    cargo: data.get("cargo"),
    area: data.get("area"),
    turno: data.get("turno"),
    status: data.get("status"),
    previsao_afastamento: data.get("previsao_afastamento") === "on",
    data_afastamento: data.get("data_afastamento"),
    causa_afastamento: data.get("causa_afastamento"),
  };
}

formNovo.addEventListener("submit", async (e) => {
  e.preventDefault();
  const payload = formToJson(formNovo);

  const res = await fetch("/api/hc", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });

  const data = await res.json();
  if (!res.ok) return showMessage(data.erro || "Erro ao salvar.", true);

  formNovo.reset();
  showMessage(data.mensagem);
  carregarTabela(busca.value);
});

window.abrirEdicao = function(id) {
  const item = cache.find(x => x.id === id);
  if (!item) return;
  formEditar.id.value = item.id;
  formEditar.nome_completo.value = item.nome_completo;
  formEditar.login.value = item.login;
  formEditar.cargo.value = item.cargo;
  formEditar.area.value = item.area;
  formEditar.turno.value = item.turno;
  formEditar.status.value = item.status;
  formEditar.previsao_afastamento.checked = item.previsao_afastamento;
  formEditar.data_afastamento.value = item.data_afastamento || "";
  formEditar.causa_afastamento.value = item.causa_afastamento || "";
  modal.classList.remove("hidden");
};

formEditar.addEventListener("submit", async (e) => {
  e.preventDefault();
  const id = formEditar.id.value;
  const payload = formToJson(formEditar);

  const res = await fetch(`/api/hc/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });

  const data = await res.json();
  if (!res.ok) return showMessage(data.erro || "Erro ao atualizar.", true);

  modal.classList.add("hidden");
  showMessage(data.mensagem);
  carregarTabela(busca.value);
});

fecharModal.addEventListener("click", () => modal.classList.add("hidden"));

busca.addEventListener("input", () => carregarTabela(busca.value));

btnExportar.addEventListener("click", () => {
  window.location.href = "/api/hc/export";
});

arquivoImport.addEventListener("change", async () => {
  const file = arquivoImport.files[0];
  if (!file) return;
  const formData = new FormData();
  formData.append("arquivo", file);

  const res = await fetch("/api/hc/import", {
    method: "POST",
    body: formData,
  });
  const data = await res.json();
  if (!res.ok) return showMessage(data.erro || "Erro na importação.", true);

  showMessage(`${data.mensagem} Inseridos: ${data.inseridos} | Atualizados: ${data.atualizados}`);
  carregarTabela(busca.value);
  arquivoImport.value = "";
});

carregarTabela();
