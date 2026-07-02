// ── Paleta de cores ──────────────────────────────────────────────
const PALETTE = {
  navy:    "#003a63",
  blue:    "#1565c0",
  teal:    "#00897b",
  orange:  "#e65100",
  red:     "#c62828",
  purple:  "#6a1b9a",
  green:   "#2e7d32",
  yellow:  "#f9a825",
  slate:   "#546e7a",
  pink:    "#ad1457",
};

const AREA_COLORS = [
  "#1565c0","#0277bd","#00838f","#2e7d32","#558b2f",
  "#f57f17","#e65100","#6a1b9a","#ad1457","#c62828",
  "#37474f","#4e342e",
];

const TURNO_COLORS = {
  "ADM":        "#37474f",
  "BLUE DAY":   "#1565c0",
  "BLUE NIGHT": "#0277bd",
  "RED DAY":    "#c62828",
  "RED NIGHT":  "#ad1457",
  "—":          "#90a4ae",
};

const STATUS_COLORS = {
  "OPERACIONAL": "#2e7d32",
  "Treinamento": "#00897b",
  "Licença":     "#f9a825",
  "Férias":      "#1976d2",
  "OFF":         "#c62828",
};

const LC_LEVEL_COLORS = {
  "LC1": "#1565c0",
  "LC3": "#00897b",
  "LC5": "#e65100",
  "EXPERT": "#6a1b9a",
  "Sem informacao": "#90a4ae",
};

// ── Estado dos filtros ───────────────────────────────────────────
const filtros = { area: "", turno: "", status: "", cargo: "", job: "", presenca: "" };
const charts  = {};

// ── Utilitários ──────────────────────────────────────────────────
function buildUrl() {
  const p = new URLSearchParams();
  if (filtros.area)   p.set("area",   filtros.area);
  if (filtros.turno)  p.set("turno",  filtros.turno);
  if (filtros.status) p.set("status", filtros.status);
  if (filtros.cargo)  p.set("cargo",  filtros.cargo);
  if (filtros.job)    p.set("job",    filtros.job);
  if (filtros.presenca) p.set("presenca", filtros.presenca);
  return `/api/hc/dashboard?${p.toString()}`;
}

function listUrl(extra = {}) {
  const p = new URLSearchParams();
  if (filtros.area)   p.set("area",   filtros.area);
  if (filtros.turno)  p.set("turno",  filtros.turno);
  if (filtros.status) p.set("status", filtros.status);
  if (filtros.cargo)  p.set("cargo",  filtros.cargo);
  if (filtros.job)    p.set("job",    filtros.job);
  if (filtros.presenca) p.set("presenca", filtros.presenca);
  Object.entries(extra).forEach(([k, v]) => { if (v) p.set(k, v); });
  return `/atualizar?${p.toString()}`;
}

function lcListUrl(extra = {}) {
  const p = new URLSearchParams();
  if (filtros.area)   p.set("area",   filtros.area);
  if (filtros.turno)  p.set("turno",  filtros.turno);
  if (filtros.status) p.set("status", filtros.status);
  if (filtros.cargo)  p.set("cargo",  filtros.cargo);
  if (filtros.job)    p.set("job",    filtros.job);
  if (filtros.presenca) p.set("presenca", filtros.presenca);
  Object.entries(extra).forEach(([k, v]) => { if (v) p.set(k, v); });
  return `/lc?${p.toString()}`;
}

function destroyChart(id) {
  if (charts[id]) { charts[id].destroy(); delete charts[id]; }
}

function datalabelsPlugin() {
  return {
    id: "datalabels_inline",
    afterDatasetsDraw(chart) {
      const ctx = chart.ctx;
      const horizontal = chart.options.indexAxis === "y";
      chart.data.datasets.forEach((ds, di) => {
        const meta = chart.getDatasetMeta(di);
        meta.data.forEach((bar, i) => {
          const val = ds.data[i];
          if (!val) return;
          ctx.save();
          ctx.font = "bold 12px Arial";
          ctx.textAlign = "center";
          ctx.textBaseline = "middle";
          const { x, y } = bar.tooltipPosition();
          const text = String(val);
          const width = ctx.measureText(text).width;

          if (horizontal) {
            let labelX = x + width / 2 + 8;
            let fillStyle = "#111827";
            if (labelX + width / 2 > chart.chartArea.right) {
              labelX = x - width / 2 - 8;
              fillStyle = "#fff";
            }
            ctx.fillStyle = fillStyle;
            ctx.fillText(text, labelX, y);
          } else {
            let labelY = y - 10;
            let fillStyle = "#111827";
            if (labelY < chart.chartArea.top + 8) {
              labelY = y + 14;
              fillStyle = "#fff";
            }
            ctx.fillStyle = fillStyle;
            ctx.fillText(text, x, labelY);
          }
          ctx.restore();
        });
      });
    }
  };
}

function maxValue(values) {
  return values.length ? Math.max(...values.map(v => Number(v) || 0)) : 0;
}

function paddedMax(values) {
  const max = maxValue(values);
  if (!max) return 5;
  return Math.ceil(max * 1.18);
}

// ── Render gráfico de barras horizontal (com rótulos externos) ───
function renderBarH(id, labels, values, colors, clickFn) {
  destroyChart(id);
  const ctx = document.getElementById(id);
  charts[id] = new Chart(ctx, {
    type: "bar",
    plugins: [datalabelsPlugin()],
    data: {
      labels,
      datasets: [{
        label: "Quantidade",
        data: values,
        backgroundColor: colors || PALETTE.blue,
        borderRadius: 4,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      indexAxis: "y",
      layout: { padding: { right: 26, top: 8, bottom: 4 } },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: ctx => ` ${ctx.parsed.x}` } }
      },
      scales: {
        x: { suggestedMax: paddedMax(values), grid: { color: "#e8edf3" }, ticks: { color: "#374151" } },
        y: { grid: { display: false }, ticks: { color: "#374151", font: { size: 11 } } }
      },
      onClick(evt, elements) {
        if (!elements.length) return;
        const label = labels[elements[0].index];
        if (clickFn) clickFn(label);
      }
    }
  });
}

// ── Render gráfico de barras vertical ────────────────────────────
function renderBarV(id, labels, values, colors, clickFn) {
  destroyChart(id);
  const ctx = document.getElementById(id);
  charts[id] = new Chart(ctx, {
    type: "bar",
    plugins: [datalabelsPlugin()],
    data: {
      labels,
      datasets: [{
        label: "Quantidade",
        data: values,
        backgroundColor: colors || PALETTE.blue,
        borderRadius: 4,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      layout: { padding: { top: 20, right: 8 } },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: ctx => ` ${ctx.parsed.y}` } }
      },
      scales: {
        y: { suggestedMax: paddedMax(values), grid: { color: "#e8edf3" }, ticks: { color: "#374151" } },
        x: { grid: { display: false }, ticks: { color: "#374151", font: { size: 11 } } }
      },
      onClick(evt, elements) {
        if (!elements.length) return;
        const label = labels[elements[0].index];
        if (clickFn) clickFn(label);
      }
    }
  });
}

// ── Render doughnut ───────────────────────────────────────────────
function renderDoughnut(id, labels, values, colors, clickFn) {
  destroyChart(id);
  const ctx = document.getElementById(id);
  charts[id] = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels,
      datasets: [{
        data: values,
        backgroundColor: colors,
        borderWidth: 2,
        borderColor: "#fff",
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: "55%",
      plugins: {
        legend: {
          position: "bottom",
          labels: { boxWidth: 14, padding: 10, font: { size: 11 } }
        },
        tooltip: { callbacks: { label: ctx => ` ${ctx.label}: ${ctx.parsed}` } }
      },
      onClick(evt, elements) {
        if (!elements.length) return;
        const label = labels[elements[0].index];
        if (clickFn) clickFn(label);
      }
    }
  });
}

// ── Render grouped bars ───────────────────────────────────────────
function renderGrouped(id, mapa, series, serieColors, clickFn) {
  destroyChart(id);
  const labels   = Object.keys(mapa);
  const datasets = series.map((name, i) => ({
    label: name,
    data: labels.map(l => mapa[l][name] || 0),
    backgroundColor: serieColors[i],
    borderRadius: 3,
  }));

  const ctx = document.getElementById(id);
  const allValues = datasets.flatMap(ds => ds.data);
  charts[id] = new Chart(ctx, {
    type: "bar",
    plugins: [datalabelsPlugin()],
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      layout: { padding: { top: 20, right: 8 } },
      plugins: {
        legend: { position: "top", labels: { boxWidth: 12, font: { size: 11 } } }
      },
      scales: {
        y: { suggestedMax: paddedMax(allValues), grid: { color: "#e8edf3" }, ticks: { color: "#374151" } },
        x: { grid: { display: false }, ticks: { color: "#374151", font: { size: 11 } } }
      },
      onClick(evt, elements) {
        if (!elements.length) return;
        const label   = labels[elements[0].index];
        const serie   = series[elements[0].datasetIndex];
        if (clickFn) clickFn(label, serie);
      }
    }
  });
}

// ── Renderiza pills de filtro ─────────────────────────────────────
function renderPills(containerId, valores, campo) {
  const el = document.getElementById(containerId);
  el.innerHTML = "";
  valores.forEach(v => {
    const btn = document.createElement("button");
    btn.className = "filter-pill" + (filtros[campo] === v ? " active" : "");
    btn.textContent = v;
    btn.onclick = () => {
      filtros[campo] = filtros[campo] === v ? "" : v;
      carregarDashboard();
    };
    el.appendChild(btn);
  });
}

function topEntries(obj, limit = 12) {
  return Object.fromEntries(Object.entries(obj || {}).slice(0, limit));
}

function seriesFromMap(mapa) {
  const found = new Set();
  Object.values(mapa || {}).forEach(row => {
    Object.keys(row || {}).forEach(k => found.add(k));
  });
  const preferred = ["LC1", "LC3", "LC5", "EXPERT", "Sem informacao"];
  return [
    ...preferred.filter(k => found.has(k)),
    ...Array.from(found).filter(k => !preferred.includes(k)).sort(),
  ];
}

function colorsForSeries(series) {
  return series.map((name, i) => LC_LEVEL_COLORS[name] || AREA_COLORS[i % AREA_COLORS.length]);
}

// ── Carregar e renderizar tudo ────────────────────────────────────
async function carregarDashboard() {
  const res  = await fetch(buildUrl());
  const data = await res.json();

  // Cards
  document.getElementById("hcTotal").textContent       = data.cards.hc_total;
  document.getElementById("hcOperacional").textContent = data.cards.hc_operacional;
  document.getElementById("pctOutbound").textContent   = `${data.cards.pct_outbound}%`;
  document.getElementById("pctInbound").textContent    = `${data.cards.pct_inbound}%`;
  document.getElementById("pctIcqa").textContent       = `${data.cards.pct_icqa}%`;

  // Pills de filtro
  renderPills("filterArea",   data.filtros_disponiveis.areas,  "area");
  renderPills("filterTurno",  data.filtros_disponiveis.turnos, "turno");
  renderPills("filterStatus", data.filtros_disponiveis.status, "status");
  renderPills("filterCargo",  data.filtros_disponiveis.cargos, "cargo");
  renderPills("filterPresenca", data.filtros_disponiveis.presencas || [], "presenca");
  renderPills("filterJob", data.filtros_disponiveis.jobs || [], "job");

  // ── HC por Área (horizontal) ────────────────────────────────
  const areaLabels = Object.keys(data.por_area);
  const areaVals   = Object.values(data.por_area);
  const areaCores  = areaLabels.map((_, i) => AREA_COLORS[i % AREA_COLORS.length]);
  renderBarH("chartArea", areaLabels, areaVals, areaCores, (label) => {
    window.location.href = listUrl({ area: label });
  });

  // ── HC por Cargo (vertical) ─────────────────────────────────
  const cargoLabels = Object.keys(data.por_cargo);
  const cargoVals   = Object.values(data.por_cargo);
  const cargoCores  = cargoLabels.map((_, i) => AREA_COLORS[i % AREA_COLORS.length]);
  renderBarV("chartCargo", cargoLabels, cargoVals, cargoCores, (label) => {
    window.location.href = listUrl({ cargo: label });
  });

  // ── Associados e PITs por turno ─────────────────────────────
  renderGrouped("chartAssociados", data.associados_e_pits,
    ["AA", "Associado", "PIT"],
    [PALETTE.teal, PALETTE.blue, PALETTE.pink],
    (turno, cargo) => {
      window.location.href = listUrl({ turno, cargo });
    }
  );

  // ── HC por Turno (doughnut) ─────────────────────────────────
  const turnoLabels = Object.keys(data.por_turno);
  const turnoVals   = Object.values(data.por_turno);
  const turnoCores  = turnoLabels.map(l => TURNO_COLORS[l] || PALETTE.slate);
  renderDoughnut("chartTurno", turnoLabels, turnoVals, turnoCores, (label) => {
    window.location.href = listUrl({ turno: label });
  });

  // ── Status (horizontal) ─────────────────────────────────────
  const statusLabels = Object.keys(data.status);
  const statusVals   = Object.values(data.status);
  const statusCores  = statusLabels.map(l => STATUS_COLORS[l] || PALETTE.slate);
  renderBarH("chartStatus", statusLabels, statusVals, statusCores, (label) => {
    window.location.href = listUrl({ status: label });
  });

  // ── HC Operacional por Turno (grouped) ──────────────────────
  renderGrouped("chartOperacionalTurno", data.operacional_por_turno,
    ["Analista", "AA", "Associado", "PIT"],
    [PALETTE.navy, PALETTE.teal, PALETTE.blue, PALETTE.pink],
    (turno, cargo) => {
      window.location.href = listUrl({ turno, cargo, status: "OPERACIONAL" });
    }
  );

  const processos = data.processos || {};
  const procCards = processos.cards || {};
  document.getElementById("procAaOperacional").textContent = procCards.aa_operacional || 0;
  document.getElementById("procAaPresentes").textContent = procCards.aa_presentes || 0;
  document.getElementById("procAaAlocados").textContent = procCards.aa_alocados || 0;
  document.getElementById("procAttendance").textContent = `${procCards.attendance_pct || 0}%`;
  document.getElementById("procSemJob").textContent = procCards.sem_job || 0;

  const procJob = processos.por_job || {};
  const procJobLabels = Object.keys(procJob);
  renderBarH("chartProcessoJob", procJobLabels, Object.values(procJob),
    procJobLabels.map((_, i) => AREA_COLORS[i % AREA_COLORS.length]),
    (job) => { window.location.href = listUrl({ job }); }
  );

  const procAreaLabels = Object.keys(processos.por_area || {});
  renderDoughnut("chartProcessoArea", procAreaLabels, Object.values(processos.por_area || {}),
    procAreaLabels.map((_, i) => AREA_COLORS[i % AREA_COLORS.length]),
    (area) => { window.location.href = listUrl({ area }); }
  );

  const attendanceTurno = processos.attendance_por_turno || {};
  const attTurnoLabels = Object.keys(attendanceTurno);
  renderBarV("chartAttendanceTurno", attTurnoLabels, attTurnoLabels.map(k => attendanceTurno[k].attendance || 0),
    attTurnoLabels.map(l => TURNO_COLORS[l] || PALETTE.slate),
    (turno) => { window.location.href = listUrl({ turno }); }
  );

  const procTurnoLabels = Object.keys(processos.por_turno || {});
  renderBarV("chartProcessoTurno", procTurnoLabels, Object.values(processos.por_turno || {}),
    procTurnoLabels.map(l => TURNO_COLORS[l] || PALETTE.slate),
    (turno) => { window.location.href = listUrl({ turno }); }
  );

  const procCargoLabels = Object.keys(processos.por_cargo || {});
  renderBarV("chartProcessoCargo", procCargoLabels, Object.values(processos.por_cargo || {}),
    procCargoLabels.map((_, i) => AREA_COLORS[i % AREA_COLORS.length]),
    (cargo) => { window.location.href = listUrl({ cargo }); }
  );

  const turnoProcesso = processos.turno_processo || {};
  const turnoProcessoSeries = seriesFromMap(turnoProcesso);
  renderGrouped("chartTurnoProcesso", turnoProcesso, turnoProcessoSeries,
    turnoProcessoSeries.map((_, i) => AREA_COLORS[i % AREA_COLORS.length]),
    (turno, job) => { window.location.href = listUrl({ turno, job }); }
  );

  const attendanceSetor = processos.attendance_por_setor || {};
  const attSetorLabels = Object.keys(attendanceSetor);
  renderBarH("chartAttendanceSetor", attSetorLabels, attSetorLabels.map(k => attendanceSetor[k].attendance || 0),
    attSetorLabels.map((_, i) => AREA_COLORS[i % AREA_COLORS.length]),
    (area) => { window.location.href = listUrl({ area }); }
  );

  const lc = data.lc || {};
  const lcCards = lc.cards || {};
  document.getElementById("lcTotalRegistros").textContent = lcCards.total_registros || 0;
  document.getElementById("lcPessoas").textContent = lcCards.pessoas_com_lc || 0;
  document.getElementById("lcProcessos").textContent = lcCards.processos || 0;
  document.getElementById("lcSemHc").textContent = lcCards.sem_hc || 0;

  const lcProcesso = topEntries(lc.por_processo, 15);
  const lcProcessoLabels = Object.keys(lcProcesso);
  const lcProcessoVals = Object.values(lcProcesso);
  renderBarH("chartLCProcesso", lcProcessoLabels, lcProcessoVals,
    lcProcessoLabels.map((_, i) => AREA_COLORS[i % AREA_COLORS.length]),
    (label) => { window.location.href = lcListUrl({ process_name: label }); }
  );

  const lcLevelLabels = Object.keys(lc.por_level || {});
  const lcLevelVals = Object.values(lc.por_level || {});
  renderBarV("chartLCLevel", lcLevelLabels, lcLevelVals,
    lcLevelLabels.map((l, i) => LC_LEVEL_COLORS[l] || AREA_COLORS[i % AREA_COLORS.length]),
    (label) => { window.location.href = lcListUrl({ lc_level: label }); }
  );

  const lcTurnoLabels = Object.keys(lc.por_turno || {});
  const lcTurnoVals = Object.values(lc.por_turno || {});
  renderDoughnut("chartLCTurno", lcTurnoLabels, lcTurnoVals,
    lcTurnoLabels.map(l => TURNO_COLORS[l] || PALETTE.slate),
    (label) => { window.location.href = lcListUrl({ turno: label }); }
  );

  const lcArea = topEntries(lc.por_area, 12);
  const lcAreaLabels = Object.keys(lcArea);
  renderBarH("chartLCArea", lcAreaLabels, Object.values(lcArea),
    lcAreaLabels.map((_, i) => AREA_COLORS[i % AREA_COLORS.length]),
    (label) => { window.location.href = lcListUrl({ area: label }); }
  );

  const lcCargo = topEntries(lc.por_cargo, 12);
  const lcCargoLabels = Object.keys(lcCargo);
  renderBarV("chartLCCargo", lcCargoLabels, Object.values(lcCargo),
    lcCargoLabels.map((_, i) => AREA_COLORS[i % AREA_COLORS.length]),
    (label) => { window.location.href = lcListUrl({ cargo: label }); }
  );

  const lcStatusLabels = Object.keys(lc.por_status || {});
  renderBarH("chartLCStatus", lcStatusLabels, Object.values(lc.por_status || {}),
    lcStatusLabels.map(l => STATUS_COLORS[l] || PALETTE.slate),
    (label) => { window.location.href = lcListUrl({ status: label }); }
  );

  const processoLevel = lc.processo_level || {};
  const processoSeries = seriesFromMap(processoLevel);
  renderGrouped("chartLCProcessoLevel", processoLevel, processoSeries, colorsForSeries(processoSeries),
    (process_name, lc_level) => { window.location.href = lcListUrl({ process_name, lc_level }); }
  );

  const turnoLevel = lc.turno_level || {};
  const turnoSeries = seriesFromMap(turnoLevel);
  renderGrouped("chartLCTurnoLevel", turnoLevel, turnoSeries, colorsForSeries(turnoSeries),
    (turno, lc_level) => { window.location.href = lcListUrl({ turno, lc_level }); }
  );

  const topLogin = topEntries(lc.top_login, 15);
  const topLoginLabels = Object.keys(topLogin);
  renderBarH("chartLCTopLogin", topLoginLabels, Object.values(topLogin),
    topLoginLabels.map((_, i) => AREA_COLORS[i % AREA_COLORS.length]),
    (login) => { window.location.href = lcListUrl({ login }); }
  );
}

document.getElementById("btnLimparFiltros").addEventListener("click", () => {
  filtros.area = filtros.turno = filtros.status = filtros.cargo = filtros.job = filtros.presenca = "";
  carregarDashboard();
});

carregarDashboard();
