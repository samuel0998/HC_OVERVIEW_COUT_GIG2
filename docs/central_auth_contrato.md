# Contrato de integração — Controle Central de Acesso (HC Overview)

A HC Overview é a autoridade única que diz **se um usuário pode acessar uma
aplicação**, **com qual perfil/permissões**, e **se isso ainda vale agora**.
Este documento é o contrato que qualquer aplicação integrada (LaborDash,
DockView, ou uma nova) precisa seguir. Implementação de referência executável
(testada): `docs/integracao_central/middleware_flask_exemplo.py`.

## 1. Conceitos e identificadores estáveis

| Conceito | Identificador estável | Onde vive |
|---|---|---|
| Usuário | `login` (minúsculo) | tabela `operadores`, banco central GIG2 |
| Aplicação | `slug` (ex.: `labordash`) | tabela `central_aplicacoes` |
| Credencial da aplicação | chave opaca `hcx_...` | tabela `central_chaves_aplicacao` (só o hash é gravado) |
| Liberação (usuário × app) | par `(usuario_login, aplicacao_id)` | tabela `central_acessos` |

**O slug da sua aplicação e a chave de API vêm de uma configuração confiável do
seu próprio servidor (variável de ambiente), nunca de um parâmetro que o
cliente manda.** A central também nunca aceita a aplicação "se identificar" no
corpo da requisição — o slug é sempre derivado da chave autenticada.

## 2. Fluxo esperado em toda requisição protegida

1. **Autentique o usuário** com o esquema da sua própria aplicação (cookie, SSO
   corporativo, o que for). Isso não é feito pela HC Overview.
2. **Valide essa credencial local** (assinatura/sessão/expiração - depende do
   seu esquema).
3. **Consulte a autorização central**: `POST /api/central/autorizar`,
   autenticado com a credencial TÉCNICA da sua aplicação (não a do usuário).
4. **Verifique a permissão exigida pela operação**, se a rota precisar de uma
   permissão específica (campo opcional `permissao_necessaria`).
5. **Libere ou negue** a requisição com base no `autorizado` da resposta.

Repita os passos 3-5 **em toda requisição protegida** — não cacheie um
resultado positivo entre requisições. Se o acesso for revogado ou o usuário
bloqueado na aba Usuários da HC Overview, a próxima chamada já reflete isso.

## 3. `POST /api/central/autorizar`

**Autenticação:** header `Authorization: Bearer <chave_da_aplicacao>`.

**Corpo da requisição:**
```json
{
  "usuario_login": "jsilva",
  "permissao_necessaria": "editar_relatorios"
}
```
`permissao_necessaria` é opcional — omita se a rota só exige estar liberado na
aplicação, sem uma permissão específica.

**Respostas:**

| HTTP | Quando | Corpo |
|---|---|---|
| `200` | Chave válida e usuário autorizado | `{"autorizado": true, "motivo": "ok", "usuario": {...}, "acesso": {...}}` |
| `403` | Chave válida, mas usuário não autorizado | `{"autorizado": false, "motivo": "...", ...}` |
| `401` | Chave ausente, inválida, revogada ou expirada | `{"erro": "..."}` |

Valores possíveis de `motivo` quando `autorizado=false`: `usuario_nao_encontrado`,
`usuario_bloqueado`, `aplicacao_inativa`, `sem_liberacao`, `liberacao_revogada`,
`liberacao_expirada`, `permissao_insuficiente`.

**Mapeamento de status na SUA aplicação** (quem decide é você, com base na
resposta):
- Seu usuário não tem sessão/credencial local válida → **401** (a central nem
  é consultada nesse caso).
- Central respondeu `403` (`autorizado: false`) → **403** pro usuário final.
- Chamada à central falhou (timeout, erro de rede) ou ela respondeu `401`
  (sua própria credencial inválida) → **503**. Nunca libere acesso aqui.

## 4. Rotas públicas (as únicas que não exigem nada acima)

- `GET /api/central/saude` — verificação básica de disponibilidade da central.
- As suas próprias rotas de login/health check, conforme o esquema da sua app.

Declare explicitamente essas exceções no seu middleware — tudo o mais (URLs
diretas, chamadas de API, downloads, rotas administrativas) passa pelo fluxo
acima.

## 5. Cadastro de aplicação e credenciais (feito por um admin na HC Overview)

Endpoints administrativos (cookie de sessão da HC Overview + usuário
`is_admin`, usados pela aba Usuários — não chamados pela sua aplicação):

- `POST /api/central/aplicacoes` — cadastra a aplicação (`slug`, `nome`,
  `perfis_disponiveis` opcional).
- `POST /api/central/aplicacoes/<id>/chaves` — gera uma credencial técnica.
  **O segredo em texto puro só aparece nesta resposta, uma vez.** Guarde-o já
  como variável de ambiente (`HC_APP_API_KEY`) no servidor da sua aplicação.
- `POST /api/central/chaves/<id>/revogar` — revoga uma credencial (passa a
  rejeitar com 401 na próxima chamada).
- `PUT /api/central/usuarios/<login>/acessos/<aplicacao_id>` — libera/atualiza
  o acesso de um usuário (perfil, permissões, expiração).
- `POST /api/central/usuarios/<login>/acessos/<aplicacao_id>/revogar` — revoga.
- `POST /api/central/usuarios/<login>/bloquear` — bloqueio GLOBAL (todas as
  aplicações), independente de liberações individuais.

## 6. O que uma chave de aplicação NÃO faz

Uma credencial técnica autentica **a aplicação**, nunca um usuário. Ela não
concede, sozinha, acesso em nome de ninguém — toda checagem ainda depende de
existir uma liberação (`central_acessos`) ativa, não expirada, pro par
usuário+aplicação. Perfis concedidos numa aplicação (ex.: "ADMIN" dentro do
LaborDash) não dão nenhum privilégio na própria HC Overview nem em outras
aplicações — são administrados separadamente.

## 7. Variáveis de ambiente que a sua aplicação precisa

| Variável | Descrição |
|---|---|
| `HC_CENTRAL_URL` | URL base da HC Overview (ex.: `https://hcoverview.exemplo.com`) |
| `HC_APP_SLUG` | Slug desta aplicação, cadastrado na HC Overview (informativo/log — a central já deriva o slug pela chave) |
| `HC_APP_API_KEY` | Credencial técnica desta aplicação (gerada uma vez, guardada só como segredo de servidor) |
| `HC_CENTRAL_TIMEOUT_SEGUNDOS` | Timeout da chamada à central (padrão 3s no exemplo) — defina um valor baixo; indisponibilidade deve falhar rápido e fechado |

Nunca coloque `HC_APP_API_KEY` no frontend, no repositório ou em log.

## 8. Autenticação por chave de segurança (YubiKey)

Além do login tradicional, a HC Overview aceita identificar um usuário pela
**chave de segurança física (YubiKey)** que ele já possui — sem senha. Isto é
**identidade de usuário**, um conceito separado da credencial técnica da
aplicação (seção 1): uma chave de segurança nunca autentica uma aplicação, e
uma `ChaveAplicacao` nunca identifica uma pessoa.

### Como funciona

Uma YubiKey em modo OTP, ao ser tocada, "digita" (via teclado USB) uma string
de até 44 caracteres (alfabeto ModHex). **Os 12 primeiros caracteres são o ID
público e ESTÁVEL daquela chave física** — não mudam nunca, nem entre toques
diferentes da mesma chave. O restante (~32 caracteres) é a parte variável, que
troca a cada toque.

**Simplificação deliberada desta entrega:** só o ID público (12 caracteres) é
conferido contra o que foi cadastrado. A parte variável do OTP **não** é
validada contra o Yubico OTP/YubiCloud. Na prática, a chave funciona como um
identificador fixo ligado à posse física do dispositivo — não como uma senha
de uso único à prova de repetição ("replay"). Quem tiver os 12 caracteres (ex.:
visto por cima do ombro, anotado em algum lugar) consegue se identificar como
o dono da chave. Trate o ID como dado sensível. Se precisar de garantia
criptográfica real de uso único no futuro, o caminho é validar o OTP completo
contra a YubiCloud (exige client id/secret próprios da Yubico) — não
implementado aqui por não haver essa exigência hoje.

### Cadastro (feito por um admin na HC Overview)

Aba Usuários → linha do operador → **Integrações** → seção **Auth — chaves de
segurança**: toque a chave no campo (ou cole os 12 caracteres do ID) e salve.
Não existe geração de chave aqui — a chave já existe fisicamente, só é
registrada contra o `usuario_login` dela.

- `POST /api/central/usuarios/<login>/chaves-fisicas` — cadastra (`otp_ou_id`,
  `apelido` opcional). 409 se a mesma chave já está ativa pra outro usuário.
- `GET /api/central/usuarios/<login>/chaves-fisicas` — lista as chaves do usuário.
- `POST /api/central/chaves-fisicas/<id>/revogar` — revoga (a chave física
  continua existindo, só deixa de identificar alguém até ser recadastrada).

### `POST /api/central/identificar-por-chave` — pra aplicações consumidoras

Resolve **quem é o dono** de uma chave de segurança apresentada. É um passo
de **identidade**, separado de **autorização** — depois de identificar o
usuário, chame `/api/central/autorizar` normalmente (seção 3) com o
`usuario_login` resolvido.

**Autenticação:** header `Authorization: Bearer <chave_da_aplicacao>` (igual ao `/autorizar`).

**Corpo:** `{"otp_ou_id": "<OTP completo digitado pela chave, ou só os 12 caracteres>"}`

**Respostas:**

| HTTP | Quando | Corpo |
|---|---|---|
| `200` | Chave reconhecida e usuário ativo | `{"identificado": true, "usuario_login": "...", "usuario": {...}}` |
| `404` | Chave não cadastrada em nenhum usuário | `{"identificado": false, "motivo": "chave_nao_encontrada"}` |
| `403` | Chave cadastrada, mas o usuário está bloqueado globalmente | `{"identificado": false, "motivo": "usuario_bloqueado_ou_nao_encontrado"}` |
| `400` | Corpo sem `otp_ou_id` válido (menos de 12 caracteres) | `{"identificado": false, "motivo": "chave_invalida"}` |
| `401` | Credencial da SUA aplicação ausente/inválida/revogada | `{"erro": "..."}` |

Use exatamente o mesmo mapeamento de status da seção 3 pro lado da sua
aplicação (401 sem credencial local, 503 se a central estiver indisponível,
nunca liberar acesso sem essa confirmação).

## 9. Extensão futura: identidade via token assinado (JWT)

O projeto atual da HC Overview usa sessão por cookie (Flask-Login) para o
próprio login de operadores — não há emissão de JWT hoje. Se, no futuro, uma
aplicação consumidora precisar de um token de identidade assinado pela HC
Overview (ex.: SSO entre apps sem repetir login), a recomendação é:

- Emitir com **RS256** (par de chaves assimétrico) — a chave **privada** fica
  só na HC Overview; as aplicações consumidoras recebem só a **chave pública**
  (endpoint dedicado, nunca a privada).
- O token carrega **só identidade** (`sub`=login, `iss`, `aud`=slug da app,
  `iat`, `exp` curto) — **nunca** permissões ou "autorizado=true" embutidos.
  A autorização continua sendo consultada em `/api/central/autorizar` a cada
  requisição, exatamente como hoje — o token só substitui "como a app sabe
  qual usuário fez a requisição", não substitui a checagem de permissão.
- Validação do lado da aplicação consumidora: assinatura, algoritmo (recusar
  `alg: none` ou HS256 inesperado), `iss`, `aud` e `exp` — nunca só decodificar.

Isso não foi implementado nesta entrega porque não havia um consumidor real
para validar contra, e introduzir chave assimétrica + distribuição de chave
pública sem uso imediato adicionaria risco sem benefício comprovado agora.
