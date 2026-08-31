const tabelaLC = document.getElementById("tabelaLC");
const totalLC = document.getElementById("totalLC");
const resumoLC = document.getElementById("resumoLC");
const buscaLC = document.getElementById("buscaLC");
const filtroProcesso = document.getElementById("filtroProcesso");
const filtroLevel = document.getElementById("filtroLevel");
const filtroAreaLC = document.getElementById("filtroAreaLC");
const filtroTurnoLC = document.getElementById("filtroTurnoLC");
const filtroStatusLC = document.getElementById("filtroStatusLC");
const filtroCargoLC = document.getElementById("filtroCargoLC");
const filtroProdutividade = document.getElementById("filtroProdutividade");
const btnLimparLC = document.getElementById("btnLimparLC");

const params = new URLSearchParams(window.location.search);
const STATUS_CLASS = {
  "OPERACIONAL": "operacional",
  "VTE": "vte",
  "VTO": "vto",
  "Treinamento": "treinamento",
  "OFF": "off",
  "Licença": "licenca",
  "Férias": "ferias",
  "Desligado": "desligado",
};

function optionize(select, values, current, label) {
  select.innerHTML = `<option value="">${label}</option>`;
  values.forEach(value => {
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = value;
    if (value === current) opt.selected = true;
    select.appendChild(opt);
  });
}

function applyInitialFilters(filtros) {
  buscaLC.value = params.get("q") || params.get("login") || "";
  filtroProdutividade.value = (params.get("produtividade") || "").toUpperCase();

  optionize(filtroProcesso, filtros.processos || [], params.get("process_name") || params.get("process") || "", "Todos os processos");
  optionize(filtroLevel, filtros.levels || [], params.get("lc_level") || params.get("level") || "", "Todos os levels");
  optionize(filtroAreaLC, filtros.areas || [], params.get("area") || "", "Todas as areas");
  optionize(filtroTurnoLC, filtros.turnos || [], params.get("turno") || "", "Todos os turnos");
  optionize(filtroStatusLC, filtros.status || [], params.get("status") || "", "Todos os status");
  optionize(filtroCargoLC, filtros.cargos || ["Associado", "PIT"], params.get("cargo") || "", "Todos os cargos");
}

function buildApiUrl() {
  const p = new URLSearchParams();
  if (buscaLC.value.trim()) p.set("q", buscaLC.value.trim());
  if (filtroProcesso.value) p.set("process_name", filtroProcesso.value);
  if (filtroLevel.value) p.set("lc_level", filtroLevel.value);
  if (filtroAreaLC.value) p.set("area", filtroAreaLC.value);
  if (filtroTurnoLC.value) p.set("turno", filtroTurnoLC.value);
  if (filtroStatusLC.value) p.set("status", filtroStatusLC.value);
  if (filtroCargoLC.value) p.set("cargo", filtroCargoLC.value);
  if (filtroProdutividade.value) p.set("produtividade", filtroProdutividade.value);
  return `/api/lc?${p.toString()}`;
}

function currentQueryUrl() {
  const qs = window.location.search.replace(/^\?/, "");
  return qs ? `/api/lc?${qs}` : "/api/lc";
}

function syncUrl() {
  const apiParams = new URLSearchParams(buildApiUrl().split("?")[1]);
  const qs = apiParams.toString();
  const next = qs ? `/lc?${qs}` : "/lc";
  window.history.replaceState({}, "", next);
}

function renderTabela(registros) {
  tabelaLC.innerHTML = "";

  registros.forEach((item, idx) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${idx + 1}</td>
      <td>${item.login || "-"}</td>
      <td>${item.nome_completo || "-"}</td>
      <td>${item.process_name || "-"}</td>
      <td><span class="badge treinamento">${item.lc_level || "-"}</span></td>
      <td>${item.cargo || "-"}</td>
      <td>${item.area || "-"}</td>
      <td>${item.turno || "-"}</td>
      <td>${item.status ? `<span class="badge ${STATUS_CLASS[item.status] || "off"}">${item.status}</span>` : "-"}</td>
      <td><span class="badge ${item.produtividade === "PRODUTIVO" ? "operacional" : "off"}">${item.produtividade === "PRODUTIVO" ? "COM LC" : "SEM LC"}</span></td>
    `;
    tabelaLC.appendChild(tr);
  });

  totalLC.textContent = `Total: ${registros.length} LC`;
}

async function carregarLC(initial = false) {
  const res = await fetch(initial ? currentQueryUrl() : buildApiUrl());
  const data = await res.json();

  if (initial) applyInitialFilters(data.filtros || {});
  renderTabela(data.registros || []);
  const resumo = data.resumo || {};
  resumoLC.textContent = `AA com LC cadastrada: ${resumo.produtivos || 0} | AA do HC sem LC cadastrada: ${resumo.improdutivos || 0}`;
  syncUrl();
}

function reloadLC() {
  carregarLC(false);
}

[buscaLC, filtroProcesso, filtroLevel, filtroAreaLC, filtroTurnoLC, filtroStatusLC, filtroCargoLC, filtroProdutividade].forEach(el => {
  el.addEventListener(el.tagName === "INPUT" ? "input" : "change", reloadLC);
});

btnLimparLC.addEventListener("click", () => {
  buscaLC.value = "";
  filtroProcesso.value = "";
  filtroLevel.value = "";
  filtroAreaLC.value = "";
  filtroTurnoLC.value = "";
  filtroStatusLC.value = "";
  filtroCargoLC.value = "";
  filtroProdutividade.value = "";
  reloadLC();
});

carregarLC(true);
