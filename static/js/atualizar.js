const tabela        = document.getElementById("tabelaHC");
const busca         = document.getElementById("busca");
const filtroStatus  = document.getElementById("filtroStatus");
const filtroArea    = document.getElementById("filtroArea");
const filtroTurno   = document.getElementById("filtroTurno");
const mensagem      = document.getElementById("mensagem");
const formEditar    = document.getElementById("formEditar");
const modal         = document.getElementById("modalEdicao");
const fecharModal   = document.getElementById("fecharModal");
const btnExportar   = document.getElementById("btnExportar");
const arquivoImport = document.getElementById("arquivoImport");
const totalRegistros = document.getElementById("totalRegistros");

let cache = [];

// Lê filtros iniciais da URL (vindos do dashboard)
const _urlParams = new URLSearchParams(window.location.search);
if (_urlParams.get("status")) filtroStatus.value = _urlParams.get("status");
if (_urlParams.get("area"))   filtroArea.value   = _urlParams.get("area");
if (_urlParams.get("turno"))  filtroTurno.value  = _urlParams.get("turno");

function showMessage(text, isError = false) {
  mensagem.textContent = text;
  mensagem.style.color = isError ? "#b91c1c" : "#166534";
  mensagem.style.background = isError ? "#fde2e2" : "#dcfce7";
  mensagem.style.padding = "10px 14px";
  mensagem.style.borderRadius = "8px";
  setTimeout(() => {
    mensagem.textContent = "";
    mensagem.style.background = "";
    mensagem.style.padding = "";
  }, 6000);
}

const STATUS_CLASS = {
  "OPERACIONAL": "operacional",
  "OFF": "off",
  "Licença": "licenca",
};

async function carregarTabela(q = "") {
  const res = await fetch(`/api/hc?q=${encodeURIComponent(q)}`);
  cache = await res.json();
  renderTabela();
}

function renderTabela() {
  const q      = busca.value.toLowerCase();
  const fStat  = filtroStatus.value;
  const fArea  = filtroArea.value;
  const fTurno = filtroTurno.value;

  const filtrado = cache.filter(item => {
    if (fStat  && item.status         !== fStat)  return false;
    if (fArea  && (item.area  || "")  !== fArea)  return false;
    if (fTurno && (item.turno || "")  !== fTurno) return false;
    if (q) {
      const haystack = [item.nome_completo, item.login, item.cargo, item.area, item.turno, item.status]
        .join(" ").toLowerCase();
      if (!haystack.includes(q)) return false;
    }
    return true;
  });

  tabela.innerHTML = "";
  filtrado.forEach((item, idx) => {
    const statusClass = STATUS_CLASS[item.status] || "off";
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${idx + 1}</td>
      <td>${item.nome_completo}</td>
      <td>${item.login || "-"}</td>
      <td>${item.cargo}</td>
      <td>${item.area || "-"}</td>
      <td>${item.turno || "-"}</td>
      <td><span class="badge ${statusClass}">${item.status}</span></td>
      <td>${item.data_afastamento || "-"}</td>
      <td><button class="btn" onclick="abrirEdicao(${item.id})">Editar</button></td>
    `;
    tabela.appendChild(tr);
  });

  totalRegistros.textContent = `Total: ${filtrado.length} colaborador${filtrado.length !== 1 ? "es" : ""}`;
}

window.abrirEdicao = function (id) {
  const item = cache.find((x) => x.id === id);
  if (!item) return;
  formEditar.id.value = item.id;
  formEditar.nome_completo.value = item.nome_completo;
  formEditar.login.value = item.login || "";
  formEditar.cargo.value = item.cargo;
  formEditar.area.value = item.area || "";
  formEditar.turno.value = item.turno || "";
  formEditar.status.value = item.status;
  formEditar.previsao_afastamento.checked = item.previsao_afastamento;
  formEditar.data_afastamento.value = item.data_afastamento || "";
  formEditar.causa_afastamento.value = item.causa_afastamento || "";
  modal.classList.remove("hidden");
};

formEditar.addEventListener("submit", async (e) => {
  e.preventDefault();
  const id = formEditar.id.value;
  const data = new FormData(formEditar);

  const payload = {
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

  const res = await fetch(`/api/hc/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  const result = await res.json();
  if (!res.ok) return showMessage(result.erro || "Erro ao atualizar.", true);

  modal.classList.add("hidden");
  showMessage(result.mensagem);
  carregarTabela(busca.value);
});

fecharModal.addEventListener("click", () => modal.classList.add("hidden"));

busca.addEventListener("input", renderTabela);
filtroStatus.addEventListener("change", renderTabela);
filtroArea.addEventListener("change", renderTabela);
filtroTurno.addEventListener("change", renderTabela);

btnExportar.addEventListener("click", () => {
  window.location.href = "/api/hc/export";
});

arquivoImport.addEventListener("change", async () => {
  const file = arquivoImport.files[0];
  if (!file) return;

  const formData = new FormData();
  formData.append("arquivo", file);

  showMessage("Importando...");

  const res = await fetch("/api/hc/import-csv", {
    method: "POST",
    body: formData,
  });

  const data = await res.json();
  if (!res.ok) return showMessage(data.erro || "Erro na importação.", true);

  let msg = `${data.mensagem} Inseridos: ${data.inseridos} | Atualizados: ${data.atualizados}`;
  if (data.erros && data.erros.length) {
    msg += ` | Erros: ${data.erros.length}`;
  }
  showMessage(msg);
  carregarTabela(busca.value);
  arquivoImport.value = "";
});

carregarTabela();
