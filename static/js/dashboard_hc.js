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
  "Licença":     "#f9a825",
  "Férias":      "#1976d2",
  "OFF":         "#c62828",
};

// ── Estado dos filtros ───────────────────────────────────────────
const filtros = { area: "", turno: "", status: "" };
const charts  = {};

// ── Utilitários ──────────────────────────────────────────────────
function buildUrl() {
  const p = new URLSearchParams();
  if (filtros.area)   p.set("area",   filtros.area);
  if (filtros.turno)  p.set("turno",  filtros.turno);
  if (filtros.status) p.set("status", filtros.status);
  return `/api/hc/dashboard?${p.toString()}`;
}

function listUrl(extra = {}) {
  const p = new URLSearchParams();
  if (filtros.area)   p.set("area",   filtros.area);
  if (filtros.turno)  p.set("turno",  filtros.turno);
  if (filtros.status) p.set("status", filtros.status);
  Object.entries(extra).forEach(([k, v]) => { if (v) p.set(k, v); });
  return `/atualizar?${p.toString()}`;
}

function destroyChart(id) {
  if (charts[id]) { charts[id].destroy(); delete charts[id]; }
}

function datalabelsPlugin() {
  return {
    id: "datalabels_inline",
    afterDatasetsDraw(chart) {
      const ctx = chart.ctx;
      chart.data.datasets.forEach((ds, di) => {
        const meta = chart.getDatasetMeta(di);
        meta.data.forEach((bar, i) => {
          const val = ds.data[i];
          if (!val) return;
          ctx.save();
          ctx.fillStyle = "#fff";
          ctx.font = "bold 11px Arial";
          ctx.textAlign = "center";
          ctx.textBaseline = "middle";
          const { x, y } = bar.tooltipPosition();
          ctx.fillText(val, x, y);
          ctx.restore();
        });
      });
    }
  };
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
      indexAxis: "y",
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: ctx => ` ${ctx.parsed.x}` } }
      },
      scales: {
        x: { grid: { color: "#e8edf3" }, ticks: { color: "#374151" } },
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
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: ctx => ` ${ctx.parsed.y}` } }
      },
      scales: {
        y: { grid: { color: "#e8edf3" }, ticks: { color: "#374151" } },
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
  charts[id] = new Chart(ctx, {
    type: "bar",
    plugins: [datalabelsPlugin()],
    data: { labels, datasets },
    options: {
      responsive: true,
      plugins: {
        legend: { position: "top", labels: { boxWidth: 12, font: { size: 11 } } }
      },
      scales: {
        y: { grid: { color: "#e8edf3" }, ticks: { color: "#374151" } },
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
    ["Associado", "PIT"],
    [PALETTE.blue, PALETTE.pink],
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
    ["Analista", "Associado", "PIT"],
    [PALETTE.navy, PALETTE.blue, PALETTE.pink],
    (turno, cargo) => {
      window.location.href = listUrl({ turno, cargo, status: "OPERACIONAL" });
    }
  );
}

document.getElementById("btnLimparFiltros").addEventListener("click", () => {
  filtros.area = filtros.turno = filtros.status = "";
  carregarDashboard();
});

carregarDashboard();
