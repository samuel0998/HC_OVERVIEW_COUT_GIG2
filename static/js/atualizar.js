// ── Elementos ────────────────────────────────────────────────────
const tabela          = document.getElementById("tabelaHC");
const buscaNome       = document.getElementById("buscaNome");
const buscaLogin      = document.getElementById("buscaLogin");
const filtroCargo     = document.getElementById("filtroCargo");
const filtroArea      = document.getElementById("filtroArea");
const filtroTurno     = document.getElementById("filtroTurno");
const filtroStatus    = document.getElementById("filtroStatus");
const mensagem        = document.getElementById("mensagem");
const formEditar      = document.getElementById("formEditar");
const modal           = document.getElementById("modalEdicao");
const modalExcluir    = document.getElementById("modalExcluir");
const fecharModal     = document.getElementById("fecharModal");
const btnExportar     = document.getElementById("btnExportar");
const arquivoImport   = document.getElementById("arquivoImport");
const totalRegistros  = document.getElementById("totalRegistros");
const modalStatus     = document.getElementById("modalStatus");
const btnPedirData    = document.getElementById("btnPedirData");

let cache = [];
let excluirId = null;

// ── URL params (vindos do dashboard) ────────────────────────────
const _p = new URLSearchParams(window.location.search);
if (_p.get("status")) filtroStatus.value = _p.get("status");
if (_p.get("area"))   filtroArea.value   = _p.get("area");
if (_p.get("turno"))  filtroTurno.value  = _p.get("turno");
if (_p.get("cargo"))  filtroCargo.value  = _p.get("cargo");

// ── Mensagem ─────────────────────────────────────────────────────
function showMessage(text, isError = false) {
  mensagem.textContent = text;
  mensagem.style.color      = isError ? "#b91c1c" : "#166534";
  mensagem.style.background = isError ? "#fde2e2" : "#dcfce7";
  mensagem.style.padding    = "10px 14px";
  mensagem.style.borderRadius = "8px";
  setTimeout(() => {
    mensagem.textContent = "";
    mensagem.style.background = mensagem.style.padding = "";
  }, 7000);
}

const STATUS_CLASS = {
  "OPERACIONAL": "operacional",
  "OFF":         "off",
  "Licença":     "licenca",
  "Férias":      "ferias",
  "Desligado":   "desligado",
};

// ── Carregar todos os dados ───────────────────────────────────────
async function carregarTabela() {
  const res = await fetch("/api/hc");
  cache = await res.json();
  renderTabela();
}

// ── Renderizar com filtros locais ─────────────────────────────────
function renderTabela() {
  const qNome  = buscaNome.value.toLowerCase();
  const qLogin = buscaLogin.value.toLowerCase();
  const fCargo  = filtroCargo.value;
  const fArea   = filtroArea.value;
  const fTurno  = filtroTurno.value;
  const fStatus = filtroStatus.value;

  const filtrado = cache.filter(item => {
    if (qNome  && !item.nome_completo.toLowerCase().includes(qNome))  return false;
    if (qLogin && !(item.login || "").toLowerCase().includes(qLogin)) return false;
    if (fCargo  && item.cargo              !== fCargo)  return false;
    if (fArea   && (item.area  || "")      !== fArea)   return false;
    if (fTurno  && (item.turno || "")      !== fTurno)  return false;
    if (fStatus && item.status             !== fStatus) return false;
    return true;
  });

  tabela.innerHTML = "";
  filtrado.forEach((item, idx) => {
    const sc  = STATUS_CLASS[item.status] || "off";
    const comentario = item.causa_afastamento
      ? `<span title="${item.causa_afastamento}" class="comment-cell">${item.causa_afastamento}</span>`
      : `<span class="comment-empty">—</span>`;
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${idx + 1}</td>
      <td>${item.nome_completo}</td>
      <td>${item.login || "-"}</td>
      <td>${item.cargo}</td>
      <td>${item.area  || "-"}</td>
      <td>${item.turno || "-"}</td>
      <td><span class="badge ${sc}">${item.status}</span></td>
      <td class="td-comment">${comentario}</td>
      <td>
        <button class="btn btn-sm" onclick="abrirEdicao(${item.id})">Editar</button>
        <button class="btn btn-sm danger" onclick="confirmarExcluir(${item.id}, '${item.nome_completo.replace(/'/g,"\\'")}')">Excluir</button>
      </td>
    `;
    tabela.appendChild(tr);
  });

  totalRegistros.textContent = `Total: ${filtrado.length} colaborador${filtrado.length !== 1 ? "es" : ""}`;
}

// ── Bloco de status dinâmico ──────────────────────────────────────
function atualizarBlocoStatus() {
  const val = modalStatus.value;
  document.getElementById("blocoLicenca").classList.add("hidden");
  document.getElementById("blocoDesligado").classList.add("hidden");
  document.getElementById("blocoOperacional").classList.add("hidden");

  if (val === "Licença" || val === "Férias") {
    document.getElementById("blocoLicenca").classList.remove("hidden");
    document.getElementById("labelLicenca").textContent = `Dados da ${val}`;
  } else if (val === "Desligado") {
    document.getElementById("blocoDesligado").classList.remove("hidden");
  } else {
    document.getElementById("blocoOperacional").classList.remove("hidden");
  }
}

modalStatus.addEventListener("change", atualizarBlocoStatus);

// Checkboxes sem data
document.getElementById("semDataInicio").addEventListener("change", function () {
  document.getElementById("dataInicioLicenca").disabled = this.checked;
  if (this.checked) document.getElementById("dataInicioLicenca").value = "";
});
document.getElementById("semDataFim").addEventListener("change", function () {
  document.getElementById("dataFimLicenca").disabled = this.checked;
  if (this.checked) document.getElementById("dataFimLicenca").value = "";
});

// ── Abrir edição ──────────────────────────────────────────────────
window.abrirEdicao = function (id) {
  const item = cache.find(x => x.id === id);
  if (!item) return;

  formEditar.id.value             = item.id;
  formEditar.nome_completo.value  = item.nome_completo;
  formEditar.login.value          = item.login || "";
  formEditar.cargo.value          = item.cargo;
  formEditar.area.value           = item.area  || "";
  formEditar.turno.value          = item.turno || "";
  formEditar.status.value         = item.status;

  // Reset checkboxes
  document.getElementById("semDataInicio").checked = false;
  document.getElementById("semDataFim").checked    = false;
  document.getElementById("dataInicioLicenca").disabled = false;
  document.getElementById("dataFimLicenca").disabled    = false;

  // Preenche campos de licença/férias
  document.getElementById("dataInicioLicenca").value  = item.data_inicio_licenca || "";
  document.getElementById("dataFimLicenca").value     = item.data_fim_licenca    || "";
  document.getElementById("descricaoLicenca").value   = item.causa_afastamento  || "";

  // Preenche campos de desligamento
  document.getElementById("dataDesligamento").value      = item.data_desligamento || "";
  document.getElementById("descricaoDesligamento").value = item.causa_afastamento || "";

  atualizarBlocoStatus();
  modal.classList.remove("hidden");
};

// ── Salvar edição ─────────────────────────────────────────────────
formEditar.addEventListener("submit", async (e) => {
  e.preventDefault();
  const id     = formEditar.id.value;
  const status = formEditar.status.value;

  const payload = {
    nome_completo: formEditar.nome_completo.value,
    login:  formEditar.login.value,
    cargo:  formEditar.cargo.value,
    area:   formEditar.area.value,
    turno:  formEditar.turno.value,
    status,
  };

  if (status === "Licença" || status === "Férias") {
    payload.data_inicio_licenca = document.getElementById("dataInicioLicenca").value || null;
    payload.data_fim_licenca    = document.getElementById("dataFimLicenca").value    || null;
    payload.causa_afastamento   = document.getElementById("descricaoLicenca").value;
  } else if (status === "Desligado") {
    payload.data_desligamento = document.getElementById("dataDesligamento").value || null;
    payload.causa_afastamento = document.getElementById("descricaoDesligamento").value;
  }

  const res = await fetch(`/api/hc/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  const result = await res.json();
  if (!res.ok) return showMessage(result.erro || "Erro ao atualizar.", true);

  modal.classList.add("hidden");
  showMessage(result.mensagem);
  carregarTabela();
});

// ── Exclusão ─────────────────────────────────────────────────────
window.confirmarExcluir = function (id, nome) {
  excluirId = id;
  document.getElementById("textoExcluir").textContent =
    `Tem certeza que deseja excluir "${nome}"? Esta ação não pode ser desfeita.`;
  modalExcluir.classList.remove("hidden");
};

document.getElementById("btnConfirmarExcluir").addEventListener("click", async () => {
  if (!excluirId) return;
  const res = await fetch(`/api/hc/${excluirId}`, { method: "DELETE" });
  const result = await res.json();
  modalExcluir.classList.add("hidden");
  excluirId = null;
  if (!res.ok) return showMessage(result.erro || "Erro ao excluir.", true);
  showMessage(result.mensagem);
  carregarTabela();
});

document.getElementById("btnCancelarExcluir").addEventListener("click", () => {
  modalExcluir.classList.add("hidden");
  excluirId = null;
});

// ── Pedir data ao RH ──────────────────────────────────────────────
btnPedirData.addEventListener("click", async () => {
  const id = formEditar.id.value;
  if (!id) return;

  const res    = await fetch(`/api/hc/${id}/pedir-data-desligamento`, { method: "POST" });
  const result = await res.json();

  if (result.mailto) {
    window.location.href = result.mailto;
    return;
  }
  if (!res.ok) return showMessage(result.erro || "Erro ao enviar e-mail.", true);
  showMessage(result.mensagem);
});

// ── Listeners de filtro ───────────────────────────────────────────
fecharModal.addEventListener("click", () => modal.classList.add("hidden"));
buscaNome.addEventListener("input",    renderTabela);
buscaLogin.addEventListener("input",   renderTabela);
filtroCargo.addEventListener("change", renderTabela);
filtroArea.addEventListener("change",  renderTabela);
filtroTurno.addEventListener("change", renderTabela);
filtroStatus.addEventListener("change", renderTabela);

// ── Exportar ──────────────────────────────────────────────────────
btnExportar.addEventListener("click", () => { window.location.href = "/api/hc/export"; });

// ── Importar CSV ──────────────────────────────────────────────────
arquivoImport.addEventListener("change", async () => {
  const file = arquivoImport.files[0];
  if (!file) return;
  const formData = new FormData();
  formData.append("arquivo", file);
  showMessage("Importando...");
  const res  = await fetch("/api/hc/import-csv", { method: "POST", body: formData });
  const data = await res.json();
  if (!res.ok) return showMessage(data.erro || "Erro na importação.", true);
  let msg = `${data.mensagem} Inseridos: ${data.inseridos} | Atualizados: ${data.atualizados}`;
  if (data.erros && data.erros.length) msg += ` | Erros: ${data.erros.length}`;
  showMessage(msg);
  carregarTabela();
  arquivoImport.value = "";
});

carregarTabela();
