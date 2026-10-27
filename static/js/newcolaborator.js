const formNovo = document.getElementById("formNovo");
const mensagem = document.getElementById("mensagem");

// ── URL params (vindos de um ticket de premissa ON em Pendências) ─
const _p = new URLSearchParams(window.location.search);
const ticketId = _p.get("ticket_id");
if (_p.get("cargo")) formNovo.cargo.value = _p.get("cargo");
if (_p.get("area"))  formNovo.area.value  = _p.get("area");
if (_p.get("turno")) formNovo.turno.value = _p.get("turno");

// ── Cola da pendência (aparece quando veio de "Resolver Pendência") ──
function _esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function carregarColaPendencia() {
  if (!ticketId) return;
  const box = document.getElementById("colaPendencia");
  try {
    const res = await fetch(`/api/hc/tickets/${encodeURIComponent(ticketId)}/cola`);
    if (!res.ok) return;
    const c = await res.json();
    const passos = (c.passos || []).map(p => `<li>${_esc(p)}</li>`).join("");
    box.innerHTML = `
      <div class="cola-head">
        <strong>📋 Cola da pendência — ${_esc(c.tipo_label)}</strong>
        <span class="cola-badge${c.vencido ? " vencido" : ""}">${c.progresso}/${c.quantidade} feito · prazo ${_esc(c.prazo || "—")}</span>
      </div>
      <p class="cola-instrucao">${_esc(c.instrucao)}</p>
      <div class="cola-rota"><span class="cola-lado">${_esc(c.destino.label)}</span></div>
      <ol class="cola-passos">${passos}</ol>
      <p class="cola-obs">A validação confere <strong>cargo, setor, escala e turno</strong>. Se algum não bater com o pedido, a pendência não é dada como resolvida.</p>
    `;
    box.classList.remove("hidden");
  } catch (e) {
    /* sem cola, segue a vida */
  }
}
carregarColaPendencia();

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
  }, 5000);
}

formNovo.addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = new FormData(formNovo);

  const payload = {
    nome_completo: data.get("nome_completo"),
    login: data.get("login"),
    cargo: data.get("cargo"),
    area: data.get("area"),
    turno: data.get("turno"),
  };

  const res = await fetch("/api/hc", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  const result = await res.json();
  if (!res.ok) return showMessage(result.erro || "Erro ao salvar.", true);

  let ticketMensagem = "";
  if (ticketId) {
    try {
      const validacaoRes = await fetch(`/api/hc/tickets/${encodeURIComponent(ticketId)}/resolver`, { method: "POST" });
      const validacao = await validacaoRes.json();
      ticketMensagem = validacaoRes.ok
        ? ` ${validacao.mensagem}`
        : ` Ticket ainda pendente: ${validacao.erro || "ação não validada."}`;
    } catch (erro) {
      ticketMensagem = " O cadastro foi salvo, mas não foi possível validar o ticket agora.";
    }
  }

  formNovo.reset();
  showMessage(`${result.mensagem}${ticketMensagem}`);
});

// ── Cadastro em massa ──────────────────────────────────────────────
const btnEnviarMassa = document.getElementById("btnEnviarMassa");
const arquivoMassa = document.getElementById("arquivoMassa");
const resultadoMassa = document.getElementById("resultadoMassa");

btnEnviarMassa.addEventListener("click", async () => {
  const arquivo = arquivoMassa.files[0];
  if (!arquivo) {
    resultadoMassa.innerHTML = '<p style="color:#b91c1c;">Escolha o arquivo do template antes de enviar.</p>';
    return;
  }
  const fd = new FormData();
  fd.append("arquivo", arquivo);
  btnEnviarMassa.disabled = true;
  resultadoMassa.innerHTML = '<p style="color:var(--muted);">Validando e cadastrando...</p>';

  try {
    const res = await fetch("/api/hc/cadastro-massa", { method: "POST", body: fd });
    const data = await res.json();
    if (res.ok) {
      resultadoMassa.innerHTML = `<p style="color:#166534;background:#dcfce7;padding:10px 14px;border-radius:8px;">✅ ${_esc(data.mensagem)}</p>`;
      arquivoMassa.value = "";
      return;
    }
    let html = `<p style="color:#b91c1c;background:#fde2e2;padding:10px 14px;border-radius:8px;">${_esc(data.erro || "Erro ao processar a planilha.")}</p>`;
    if (data.erros && data.erros.length) {
      html += `<div class="table-wrap" style="max-height:320px;margin-top:10px;"><table>
        <thead><tr><th>Linha</th><th>Nome</th><th>Problema(s)</th></tr></thead>
        <tbody>${data.erros.map(e => `<tr>
          <td>${e.linha}</td><td>${_esc(e.nome)}</td><td style="color:#b91c1c;">${e.erros.map(_esc).join("<br>")}</td>
        </tr>`).join("")}</tbody></table></div>`;
    }
    resultadoMassa.innerHTML = html;
  } catch (err) {
    resultadoMassa.innerHTML = '<p style="color:#b91c1c;">Erro de comunicação ao enviar a planilha.</p>';
  } finally {
    btnEnviarMassa.disabled = false;
  }
});
