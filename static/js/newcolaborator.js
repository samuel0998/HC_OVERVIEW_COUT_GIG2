const formNovo = document.getElementById("formNovo");
const mensagem = document.getElementById("mensagem");

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
    status: data.get("status"),
    previsao_afastamento: data.get("previsao_afastamento") === "on",
    data_afastamento: data.get("data_afastamento"),
    causa_afastamento: data.get("causa_afastamento"),
  };

  const res = await fetch("/api/hc", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  const result = await res.json();
  if (!res.ok) return showMessage(result.erro || "Erro ao salvar.", true);

  formNovo.reset();
  showMessage(result.mensagem);
});
