# Prompt pronto — integrar uma aplicação ao controle central (HC Overview)

Cole o bloco abaixo (seção "PROMPT") na sessão de IA que está trabalhando no
repositório da OUTRA aplicação (a que vai consumir a autorização central).
Antes de colar, copie também pra dentro daquele repositório estes dois
arquivos deste projeto, e referencie os caminhos no prompt:

- `docs/central_auth_contrato.md`
- `docs/integracao_central/middleware_flask_exemplo.py`

Se preferir não copiar arquivos, o prompt abaixo já embute o essencial do
contrato inline — funciona sozinho, só fica mais enxuto com os arquivos anexos.

---

## PROMPT

```
Preciso integrar esta aplicação ao controle centralizado de acesso de uma
aplicação externa chamada HC Overview. A HC Overview é a autoridade: ela diz
se um usuário (identificado pelo "login") pode acessar ESTA aplicação, com
qual perfil/permissões, e se isso ainda vale agora. Esta aplicação NUNCA
decide autorização sozinha - só consulta a central a cada requisição protegida.

### 1. Analise antes de alterar
Antes de escrever código, inspecione este repositório: qual stack/framework,
como ele autentica usuários hoje (sessão, JWT, OAuth, API key...), onde ficam
as rotas que precisam de autenticação, se já existe algum middleware/decorator
de autorização, e como são geridas variáveis de ambiente/segredos aqui. Não
presuma um framework específico - implemente a solução equivalente na stack
que você encontrar. Apresente brevemente o que vai mudar antes de aplicar.

### 2. Contrato da API central (a HC Overview já implementa este lado - você só consome)

Endpoint único que importa pra esta aplicação: POST {HC_CENTRAL_URL}/api/central/autorizar

Autenticação: header "Authorization: Bearer <HC_APP_API_KEY>" - essa chave
identifica QUAL aplicação está chamando (nunca escolha isso no corpo da
requisição; a central deriva a aplicação da própria chave).

Corpo da requisição (JSON):
{
  "usuario_login": "<login do usuário já autenticado NESTA aplicação>",
  "permissao_necessaria": "<opcional - string de uma permissão específica>"
}

Respostas:
- 200 => {"autorizado": true, "motivo": "ok", "usuario": {...}, "acesso": {"perfil":, "permissoes": [...], "status":, "expira_em":}}
- 403 => {"autorizado": false, "motivo": "usuario_nao_encontrado" | "usuario_bloqueado" | "aplicacao_inativa" | "sem_liberacao" | "liberacao_revogada" | "liberacao_expirada" | "permissao_insuficiente"}
- 401 => {"erro": "..."} -> a credencial DESTA aplicação (HC_APP_API_KEY) está ausente/inválida/revogada/expirada - é erro de configuração do lado desta app, não do usuário.

Também existe GET {HC_CENTRAL_URL}/api/central/saude (pública, sem auth) só
pra checagem básica de que a central está no ar - devolve {"status":"ok"}.

### 2.1 Opcional - login por chave de segurança (YubiKey) em vez de senha
SÓ implemente isto se eu pedir explicitamente que esta aplicação aceite login
pela chave física. Fluxo: o campo de login recebe o texto que a chave YubiKey
"digita" sozinha ao ser tocada (até 44 caracteres); chame primeiro

POST {HC_CENTRAL_URL}/api/central/identificar-por-chave
Autenticação: mesmo header Bearer da seção 2. Corpo: {"otp_ou_id": "<o que foi digitado>"}
Respostas: 200 => {"identificado": true, "usuario_login": "...", "usuario": {...}}
           404 => chave não cadastrada em ninguém
           403 => chave cadastrada, mas usuário bloqueado
           401 => sua própria credencial está inválida (mesmo tratamento da seção 3)

Isso resolve IDENTIDADE (quem é a pessoa), não AUTORIZAÇÃO - depois de receber
o usuario_login aqui, continue o fluxo normal da seção 3 chamando /autorizar
com esse login antes de liberar qualquer coisa. Nunca pule essa segunda etapa.

### 3. Fluxo obrigatório em toda requisição protegida (URL direta, API, download, rota administrativa - tudo)
1. Autentique o usuário com o esquema JÁ EXISTENTE desta aplicação.
2. Valide essa credencial local (sessão/token/assinatura, o que for).
3. Chame POST /api/central/autorizar com o login do usuário já autenticado.
4. Se a rota exigir uma permissão específica, mande "permissao_necessaria".
5. Decida com base na resposta:
   - Sem credencial local válida -> 401 (nem chega a chamar a central).
   - Central respondeu autorizado:false -> 403.
   - Chamada à central falhou (timeout/erro de rede) OU ela respondeu 401
     (nossa própria chave está ruim) -> 503. NUNCA libere acesso neste caso.

Implemente isso como um middleware/decorator reutilizável, não repetido rota a
rota. NÃO cacheie um resultado "autorizado" entre requisições - consulte a
central do zero sempre (revogação/bloqueio precisam valer na próxima chamada).

### 4. Configuração (variáveis de ambiente - nunca hardcoded, nunca do cliente)
- HC_CENTRAL_URL - URL base da HC Overview.
- HC_APP_SLUG - identificador desta aplicação (informativo/log).
- HC_APP_API_KEY - a credencial técnica (segredo - nunca no frontend, repositório ou log).
- HC_CENTRAL_TIMEOUT_SEGUNDOS - timeout curto pra chamada à central (ex.: 3).

### 5. Declare as exceções
As únicas rotas que NÃO passam pelo fluxo acima: login/health check desta
própria aplicação. Liste essas rotas explicitamente no código - não deixe
"tudo que não bater em nada" passar aberto por omissão.

### 6. Valide a implementação
Teste e me mostre o resultado de:
- Usuário com acesso liberado consegue usar a rota protegida.
- Usuário sem liberação recebe 403.
- HC_APP_API_KEY errada ou ausente -> 503 pro usuário final (não libera).
- Simule a central fora do ar (timeout/erro de conexão) -> 503, não libera.
- Rota protegida não responde o conteúdo sem passar pela checagem central
  (teste batendo direto na rota sem contexto de autorização).

### 7. Ao concluir, me informe
Arquivos alterados, como configurar as variáveis de ambiente neste servidor, e
como eu testo manualmente (um exemplo de curl pra uma rota protegida já
integrada).

Referência de implementação (se eu tiver anexado): docs/central_auth_contrato.md
e docs/integracao_central/middleware_flask_exemplo.py (exemplo em Flask -
adapte pro framework real deste projeto; o contrato HTTP é o que precisa valer,
não a linguagem do exemplo).
```

---

## Instruções de conexão (passo a passo, feito por você, não pela IA)

### Passo 1 — Cadastrar a aplicação e gerar a chave na HC Overview
1. Entre na HC Overview como admin (EXPERT/HARD-EXPERT) → aba **Usuários**.
2. Card "Aplicações integradas" → **+ Nova aplicação** → informe nome e slug
   (ex.: `labordash`). Perfis são opcionais.
3. Na linha da aplicação → **Chaves** → digite `nova` → dê um rótulo (ex.:
   `producao`). **Copie o segredo mostrado agora** — ele não aparece de novo.

### Passo 2 — Testar conectividade antes de mexer em código
Confirma que a outra aplicação consegue alcançar a HC Overview pela rede:

```bash
curl -s https://SEU-HC-OVERVIEW/api/central/saude
# esperado: {"status":"ok"}
```

### Passo 3 — Testar a checagem de autorização manualmente
Troque `<SEGREDO>` pelo valor copiado no Passo 1 e `<LOGIN>` por um login real
já liberado (ou não) pra essa aplicação:

```bash
curl -s -X POST https://SEU-HC-OVERVIEW/api/central/autorizar \
  -H "Authorization: Bearer <SEGREDO>" \
  -H "Content-Type: application/json" \
  -d '{"usuario_login": "<LOGIN>"}'
```
- Deve vir `200` + `"autorizado": true` se esse login já tem liberação pra
  essa aplicação (configure em Usuários → Integrações antes de testar).
- Deve vir `403` + `"motivo": "sem_liberacao"` se ainda não liberou ninguém.
- Deve vir `401` se o segredo colado estiver errado.

Só depois de ver esses três resultados batendo é que vale a pena rodar o
prompt da seção anterior — você já confirmou que a rede/credencial funcionam,
então qualquer erro depois disso é na implementação do middleware, não na
conexão.

### Passo 3.5 — (Opcional) Testar a identificação por chave de segurança (YubiKey)
Só se a sua aplicação vai aceitar login pela chave física (YubiKey) em vez de
usuário/senha próprios. Cadastre antes uma chave de teste em Usuários →
Integrações → **Auth — chaves de segurança**, depois:

```bash
curl -s -X POST https://SEU-HC-OVERVIEW/api/central/identificar-por-chave \
  -H "Authorization: Bearer <SEGREDO>" \
  -H "Content-Type: application/json" \
  -d '{"otp_ou_id": "<OTP digitado pela chave, ou só os 12 primeiros caracteres>"}'
```
- `200` + `"identificado": true` + `usuario_login` → use esse login no Passo 3
  (`/autorizar`) pra decidir a permissão, exatamente como um login normal.
- `404` → chave não cadastrada em ninguém ainda.

Isto é **identidade**, não autorização — sempre chame `/autorizar` depois de
identificar, antes de liberar qualquer coisa. Ver seção 8 de
`docs/central_auth_contrato.md` para o contrato completo.

### Passo 4 — Liberar os usuários reais
Aba Usuários → linha do operador → **Integrações** → preencha perfil/
permissões/expiração na linha da aplicação → **Liberar**.

### Passo 5 — Confirmar revogação em produção
Depois de integrado, revogue o acesso de um usuário de teste (botão
**Revogar** ou **Bloquear globalmente**) e confirme que a próxima requisição
dele na outra aplicação já nega — sem precisar reiniciar nada dos dois lados.
