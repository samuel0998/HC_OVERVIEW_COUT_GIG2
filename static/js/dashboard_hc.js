async function carregarDashboard() {
  const res = await fetch("/api/hc/dashboard");
  const data = await res.json();

  document.getElementById("hcTotal").textContent = data.cards.hc_total;
  document.getElementById("hcOperacional").textContent = data.cards.hc_operacional;
  document.getElementById("pctOutbound").textContent = `${data.cards.pct_outbound}%`;
  document.getElementById("pctInbound").textContent = `${data.cards.pct_inbound}%`;
  document.getElementById("pctIcqa").textContent = `${data.cards.pct_icqa}%`;

  renderBar("chartArea", Object.keys(data.por_area), Object.values(data.por_area), true);
  renderBar("chartCargo", Object.keys(data.por_cargo), Object.values(data.por_cargo), false);
  renderPie("chartTurno", Object.keys(data.por_turno), Object.values(data.por_turno));
  renderBar("chartStatus", Object.keys(data.status), Object.values(data.status), true);
  renderGrouped(data.associados_e_pits);
}

function renderBar(id, labels, values, horizontal = false) {
  new Chart(document.getElementById(id), {
    type: "bar",
    data: {
      labels,
      datasets: [{ label: "Quantidade", data: values }]
    },
    options: {
      responsive: true,
      indexAxis: horizontal ? "y" : "x",
      plugins: { legend: { display: false } }
    }
  });
}

function renderPie(id, labels, values) {
  new Chart(document.getElementById(id), {
    type: "doughnut",
    data: {
      labels,
      datasets: [{ data: values }]
    },
    options: { responsive: true }
  });
}

function renderGrouped(mapa) {
  const labels = Object.keys(mapa);
  const associados = labels.map(l => mapa[l]["Associado"]);
  const pits = labels.map(l => mapa[l]["PIT"]);

  new Chart(document.getElementById("chartAssociados"), {
    type: "bar",
    data: {
      labels,
      datasets: [
        { label: "Associado", data: associados },
        { label: "PIT", data: pits },
      ]
    },
    options: { responsive: true }
  });
}

carregarDashboard();
