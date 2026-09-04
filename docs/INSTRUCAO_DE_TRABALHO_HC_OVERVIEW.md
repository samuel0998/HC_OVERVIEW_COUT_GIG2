# Instrução de Trabalho — HC Overview
**Sistema de Gestão de Headcount | ID Logistics – GIG2 / IXD-CNF2**
**Versão:** 1.0 | **Classificação:** Uso Interno

---

## 1. Objetivo

O **HC Overview** é o sistema oficial de gestão de Headcount (HC) da operação. Ele centraliza o controle de todos os colaboradores (AA, Associado, PIT, Analista, Supervisor, Líder, Técnico, Fiscal, Coordenador e Gerente), seus status operacionais, alocações de turno e área, Learning Curve (LC), pendências cadastrais e tickets de RH (VTO/VTE), substituindo planilhas manuais e eliminando retrabalho.

---

## 2. Acesso ao Sistema

### 2.1 Login
- Acesse pelo navegador no endereço fornecido pelo time de TI/RME.
- Use seu **login Amazon** e senha cadastrada pelo administrador.
- Caso não consiga acessar, solicite ao nível **EXPERT** que verifique sua permissão na tela **Usuários**.

### 2.2 Níveis de Acesso

| Nível | O que pode fazer |
|-------|-----------------|
| **LC1** | Somente Dashboard e gráficos |
| **LC3** | Dashboard + Novo HC + LIST + Pendências |
| **LC5** | Tudo exceto Histórico e Excluir colaborador |
| **EXPERT** | Acesso total: inclui Histórico, Excluir, Usuários e funções administrativas |

> O nível é configurado pelo EXPERT na tela **Usuários → Gerenciar Permissões**.

---

## 3. Navegação Principal

Após o login, a barra superior exibe os módulos disponíveis conforme seu nível:

| Módulo | Acesso mínimo | Descrição |
|--------|--------------|-----------|
| **Início** | Todos | Tela inicial com atalhos e alerta de pendências |
| **Novo HC** | LC3+ | Cadastrar novo colaborador |
| **LIST** | LC3+ | Lista completa, edição, importação e exportação |
| **Pendências** | LC3+ | Pendências cadastrais + tickets de premissas + tickets RH |
| **Dashboard** | LC1+ | Indicadores e gráficos em tempo real |
| **LC** | LC1+ | Learning Curve dos colaboradores |
| **Histórico** | EXPERT | Auditoria completa de movimentações |
| **Usuários** | EXPERT | Gerenciar permissões e horários de turno |

---

## 4. Cadastro de Novo Colaborador

**Caminho:** Início → Novo HC

### 4.1 Campos obrigatórios
- **Nome completo** — nome conforme crachá
- **Cargo** — selecione: AA, Associado, PIT, Analista, Supervisor, Líder, Técnico, Fiscal, Coordenador ou Gerente

### 4.2 Campos opcionais
- **Login Amazon** — necessário para integração com LC e tickets
- **Área** — INBOUND, OUTBOUND, TRANSFER IN, TRANSFER OUT, ICQA, INSUMOS, LEARNING, LP, FACILITIES, RME, SUPORTE, C-RET, TOM, ADM
- **Turno** — BLUE DAY, BLUE NIGHT, RED DAY, RED NIGHT, ADM

### 4.3 Regras automáticas no cadastro
- Todo colaborador novo entra com status **Treinamento** automaticamente.
- **PIT** entra com turno **ADM** por padrão.
- O sistema converte automaticamente para **OPERACIONAL** após:
  - **AA/Associado:** 2 dias de cadastro
  - **PIT:** 5 dias de cadastro (turno é limpo para alocação manual)

---

## 5. LIST — Lista Completa do HC

**Caminho:** Início → LIST

### 5.1 Filtros disponíveis
- Pesquisa por **nome** ou **login** (campo de texto livre)
- Filtros por **cargo**, **área**, **turno** e **status**

### 5.2 Edição de colaborador
1. Localize o colaborador na tabela.
2. Clique no botão **Editar** (ícone de lápis).
3. Altere os campos desejados no modal.
4. Clique em **Salvar alteração**.

### 5.3 Status disponíveis e suas regras

| Status | Descrição | Regra especial |
|--------|-----------|----------------|
| **OPERACIONAL** | Presente e apto para trabalho | — |
| **Treinamento** | Recém-admitido em período de integração | Vira OPERACIONAL automaticamente (2d AA / 5d PIT) |
| **Ausência** | Falta no dia | Dura 24h; volta para OPERACIONAL no dia seguinte automaticamente |
| **Licença** | Afastamento médico ou pessoal | Requer data de início e fim + descrição obrigatória |
| **Férias** | Período de férias | Requer data de início e fim + descrição obrigatória |
| **Desligado** | Colaborador desligado | Requer data de desligamento + motivo obrigatório |
| **OFF** | Pendência vencida sem data definida | Gerado automaticamente após prazo de terça-feira |

> **Atenção:** Licença, Férias e Desligado com data futura ficam **agendados** — o status só muda no dia marcado. O colaborador continua OPERACIONAL até lá.

### 5.4 Desligamento
- Ao selecionar **Desligado**, informe a data e o motivo.
- Use o botão **📧 Pedir Data ao RH** para enviar e-mail automático ao RH solicitando a data de desligamento.
- Na data marcada, o colaborador é **arquivado automaticamente** no Histórico Operacional e removido da lista ativa.

### 5.5 Importação CSV
1. Clique em **Importar CSV**.
2. Selecione o arquivo `.csv` com as colunas: `Nome`, `Login`, `Cargo`, `Área`, `Turno`, `Status` (e opcionalmente `Presente`, `Job`, `Hora Extra`, `Descrição`, `Liberação`).
3. O sistema **substitui toda a base** pelos dados do arquivo.
4. Jobs (processos) existentes são preservados automaticamente se não estiverem no CSV.

### 5.6 Exportação Excel
- Clique em **Exportar Excel** para baixar a base atual filtrada em `.xlsx`.
- O arquivo inclui: ID, Nome, Login, Cargo, Área, Turno, Status, Chamada, Job, Hora Extra, Status Liberação, Previsão Afastamento, Data Afastamento, Descrição, datas de criação e atualização.

---

## 6. Chamada (Presença no FC)

A chamada controla quem está **fisicamente presente no FC** no turno atual.

- **Presente (SIM):** colaborador está no FC e conta para a capacidade operacional.
- **Ausente (NÃO):** colaborador não está no FC naquele momento.

### 6.1 Reset automático por virada de turno
- O administrador configura o **horário de reset** de cada turno na tela **Usuários → Configuração de Shifts**.
- Na virada do turno, **todos os colaboradores OPERACIONAIS voltam para Presente automaticamente**.
- Apenas a chamada é resetada — status, área e turno não são alterados.

---

## 7. Pendências

**Caminho:** Início → Pendências

A tela de Pendências reúne **três tipos** de itens que precisam de ação:

### 7.1 Pendências Cadastrais
Colaboradores com dados incompletos que precisam de ação até **toda terça-feira**:

| Situação | O que fazer |
|----------|-------------|
| Licença/Férias sem data | Clicar em **Definir data** e preencher início e fim |
| Desligamento sem data | Clicar em **Definir data** e informar a data de desligamento |
| PIT OPERACIONAL sem turno | Clicar em **Alocar turno** e definir o turno do PIT |
| Status OFF com `off_origem` | Colaborador virou OFF por prazo vencido — ainda precisa de data |

> Após o prazo de terça-feira, o status vira **OFF** automaticamente, mas o colaborador **continua aparecendo em Pendências** até a data ser definida.

### 7.2 Tickets de Premissas (LS · LT · TOFF · RP · ON)
Tickets gerados pela ferramenta de planejamento de premissas (gig2_hc_premises):

| Tipo | Descrição | Quem resolve |
|------|-----------|-------------|
| **LS** (Labor Share) | Compartilhamento de HC entre setores | RME do setor de origem |
| **LT** (Labor Transfer) | Transferência definitiva de HC | RME do setor de origem |
| **TOFF** (Turn Off) | Redução de HC (desligamento) | RME do setor |
| **RP** (Ramp Down) | Redução programada de HC | RME do setor |
| **ON** (New Hire) | Contratação de novo HC | EXPERT |

**Prazo:** LS e LT vencem na própria data solicitada (`work_date`), no horário configurado para o shift de destino. Só depois desse horário ficam **Não conforme**. Os demais tipos mantêm a antecedência de 3 dias.

No **LS**, os colaboradores validados ficam com retorno automático agendado para `end_date`, recuperando o setor e a escala de origem.

**Como resolver:**
1. Clique em **Resolver Pendência** → vai direto para o LIST filtrado pelo turno/setor do responsável.
2. Execute a ação no HC (transferência, desligamento, novo cadastro).
3. Clique em **Validar conclusão** → o sistema verifica automaticamente se a ação foi registrada no histórico.

### 7.3 Tickets RH — VTO / VTE
Solicitações abertas por AA/PIT via portal externo (tabela `portal_ticket_claims`):

| Tipo | Descrição | Validação para resolver |
|------|-----------|------------------------|
| **VTO** (Voluntary Time Off) | Colaborador solicita ausência voluntária | Colaborador deve estar com status **Ausência** no dia |
| **VTE** (Voluntary Time Extension) | Colaborador solicita trabalho em outro setor/turno | Aloca o colaborador no setor/turno de destino por **12 horas**, depois reverte automaticamente |

**Responsável:** RME cadastrado na área.

**Como resolver:**
1. Clique em **Resolver Pendência** → vai direto para o LIST filtrado pelo login do solicitante.
2. Verifique o status do colaborador conforme o tipo de ticket.
3. Clique em **Validar / Rejeitar** → confirme a resolução ou rejeite com observação.

> **VTE:** Ao resolver, o colaborador é automaticamente alocado para o setor/turno de destino. Após 12 horas, o sistema reverte para o setor/turno de origem sem necessidade de ação manual.

---

## 8. Dashboard

**Caminho:** Início → Dashboard

Painel de indicadores em tempo real com filtros por **Área**, **Turno**, **Status** e **Cargo** (suporta múltipla seleção com Ctrl+clique).

### 8.1 Cards principais
- **HC Total** — total de colaboradores na base
- **HC Operacional** — colaboradores com status OPERACIONAL
- **% Outbound** — percentual do HC alocado em áreas de saída (OUTBOUND, TRANSFER OUT, INSUMOS, LP)
- **% Inbound** — percentual do HC alocado em áreas de entrada (INBOUND, TRANSFER IN, C-RET)
- **% ICQA** — percentual do HC alocado em ICQA

### 8.2 Gráficos de HC
- HC por Área
- Associados e PITs por turno
- HC por Cargo
- HC por Turno
- Distribuição de Status
- HC Operacional por Turno (Analista, AA, Associado, PIT)

### 8.3 Seção LC Atual
- **LC Registros** — total de registros de Learning Curve
- **Pessoas com LC** — colaboradores únicos com LC cadastrada
- **Processos LC** — quantidade de processos distintos
- **AA sem LC** — AA/Associados OPERACIONAIS sem nenhum processo de LC

**Gráficos LC:**
- LC por Processo, por Level, por Turno, por Área, por Cargo, por Status HC
- Processo por Level (cruzamento)
- Turno por Level
- Top 15 Logins por quantidade de LC

---

## 9. LC — Learning Curve

**Caminho:** Dashboard → LC (ou menu LC)

### 9.1 O que é
Registro do nível de capacitação (LC Level) de cada colaborador por processo operacional. Permite identificar quem está produtivo (tem LC) e quem está improdutivo (sem LC).

### 9.2 Filtros
- Pesquisa livre por login, processo, nome ou cargo
- Filtros por Processo, LC Level, Área, Turno, Status HC, Cargo
- Filtro de Produtividade: **Com LC** / **Sem LC** / **Ambos**

### 9.3 Importação da base de LC
1. Clique em **Importar base de LC** no LIST.
2. Selecione o arquivo `.xlsx` exportado do sistema de LC (colunas: Login, Process Name, LC Level).
3. O sistema descarta registros de logins não encontrados no HC.
4. A base anterior é substituída completamente.

### 9.4 Exportação
- Clique em **Exportar LC Excel** para baixar a base atual de LC em `.xlsx`.

---

## 10. Histórico

**Caminho:** Início → Histórico *(somente EXPERT)*

### 10.1 Registro de Atividades
Auditoria completa de todas as ações realizadas no sistema:

| Tipo | Descrição |
|------|-----------|
| **Adição** | Novo colaborador cadastrado |
| **Edição** | Dados do colaborador alterados |
| **Edição de Status** | Status do colaborador alterado |
| **Exclusão** | Colaborador removido da base |
| **Desligamento Automático** | Colaborador arquivado automaticamente pelo sistema |

Exibe: data/hora, tipo, colaborador afetado, usuário que realizou a ação e descrição detalhada.

### 10.2 Histórico Operacional
Arquivo de colaboradores desligados. Mantém: nome, login, cargo, área, turno, data de desligamento, motivo, data de arquivamento e quem arquivou.

---

## 11. Usuários e Permissões

**Caminho:** Início → Usuários *(somente EXPERT)*

### 11.1 Gerenciar permissões
1. Localize o operador pelo login ou nome.
2. Clique em **Editar**.
3. Defina **Acesso ao HC Overview** (Permitido / Bloqueado) e o **Nível** (LC1, LC3, LC5, EXPERT).
4. Clique em **Salvar**.

> Os operadores são importados da tabela central `operadores` — não é necessário criar usuários manualmente.

### 11.2 Configuração de Shifts (horários de reset)
1. Na seção **Configuração de Shifts**, defina o horário de reset para cada turno (BLUE DAY, BLUE NIGHT, RED DAY, RED NIGHT, ADM).
2. Clique em **Salvar horários**.
3. Na hora configurada, a chamada de todos os colaboradores OPERACIONAIS volta para **Presente** automaticamente.

---

## 12. Automações do Sistema

O sistema executa as seguintes ações automáticas sem necessidade de intervenção manual:

| Automação | Quando ocorre | O que faz |
|-----------|--------------|-----------|
| **Virada de Treinamento** | Diariamente | AA/Associado → OPERACIONAL após 2 dias; PIT → OPERACIONAL após 5 dias |
| **Retorno de Ausência** | Dia seguinte | Colaborador com Ausência volta para OPERACIONAL automaticamente |
| **Ativação de status agendado** | Na data marcada | Licença/Férias/Desligado agendados passam a valer no dia configurado |
| **Retorno de Licença/Férias** | Na data de fim | Colaborador volta para OPERACIONAL ao término do período |
| **Arquivamento de desligados** | Na data de desligamento | Colaborador é movido para o Histórico Operacional e removido da lista ativa |
| **Virada para OFF** | Toda terça-feira | Licença/Férias/Desligado sem data definida viram OFF (continuam em Pendências) |
| **Reset de chamada** | Horário configurado | Todos os OPERACIONAIS voltam para Presente na virada do turno |
| **Reversão de VTE** | 12h após resolução | Colaborador retorna ao setor/turno de origem automaticamente |

---

## 13. Multi-FC (Múltiplos Centros de Distribuição)

O sistema suporta múltiplos FCs (ex.: GIG2, IXD-CNF2) com bases de dados independentes.

- O FC ativo é exibido no cabeçalho do sistema.
- Cada FC tem sua própria base de colaboradores, LC, tickets e histórico.
- A troca de FC é feita via sessão — os dados exibidos sempre correspondem ao FC selecionado.

---

## 14. Benefícios do Sistema

### Operacionais
- **Visibilidade em tempo real** do HC disponível por turno, área e cargo
- **Eliminação de planilhas manuais** — uma única fonte de verdade para toda a operação
- **Alertas automáticos** de pendências na tela inicial, sem necessidade de verificação manual
- **Chamada digital** com reset automático por virada de turno, eliminando o processo manual de chamada

### Gestão de Pessoas
- **Controle completo do ciclo do colaborador:** admissão → treinamento → operacional → afastamento → desligamento
- **Agendamento de status:** Licença, Férias e Desligamento podem ser programados com antecedência
- **Histórico de desligados** preservado para consultas futuras e auditorias
- **Integração com LC:** identifica imediatamente quem está produtivo e quem precisa de capacitação

### Conformidade e Auditoria
- **Rastreabilidade total:** toda ação é registrada com usuário, data/hora e dados antes/depois
- **Controle de prazos:** prazo de terça-feira para definição de datas com alerta visual e virada automática para OFF
- **Tickets de premissas integrados:** validação automática das ações no HC contra os tickets de planejamento (LS, LT, TOFF, RP, ON)
- **Tickets RH (VTO/VTE):** resolução rastreada com validação de regras de negócio

### Segurança e Controle de Acesso
- **Níveis de acesso granulares** (LC1, LC3, LC5, EXPERT) — cada usuário vê e faz apenas o que é necessário para sua função
- **Integração com a tabela central de operadores** — sem criação manual de usuários
- **Proteção de dados:** colaboradores desligados são arquivados, não excluídos permanentemente

### Eficiência Operacional
- **Dashboard com filtros dinâmicos** para análise rápida por área, turno, cargo e status
- **Importação/exportação Excel e CSV** para integração com outros sistemas
- **Resolução de tickets com um clique:** botão "Resolver Pendência" leva direto ao colaborador no LIST
- **Reversão automática de VTE** após 12 horas — sem risco de esquecer de reverter manualmente

---

## 15. Fluxo Resumido por Perfil

### Gestor / Supervisor (LC3 ou LC5)
```
Início do turno:
1. Acesse Início → verifique o banner de pendências
2. Acesse Pendências → resolva pendências cadastrais e tickets RH
3. Acesse LIST → faça a chamada (marque ausentes)
4. Cadastre novos colaboradores se necessário (Novo HC)

Durante o turno:
5. Atualize status de colaboradores conforme necessário (Ausência, Licença, etc.)
6. Resolva tickets de premissas (LS, LT, TOFF, RP, ON) dentro do prazo

Fim do turno:
7. Exporte o HC se necessário (Exportar Excel)
```

### Analista / RME (LC1 ou LC3)
```
1. Acesse Dashboard → monitore indicadores de HC e LC
2. Acesse LC → verifique produtividade e identifique AA sem LC
3. Importe base de LC atualizada quando disponível
4. Acesse Pendências → resolva tickets RH (VTO/VTE) sob sua responsabilidade
```

### Administrador EXPERT
```
1. Configure permissões de novos usuários (Usuários → Editar)
2. Configure horários de reset de turno (Usuários → Configuração de Shifts)
3. Monitore o Histórico para auditoria de movimentações
4. Resolva tickets ON (New Hire) em Pendências
5. Execute processamento manual de status se necessário (/api/admin/processar-status)
```

---

## 16. Glossário

| Termo | Significado |
|-------|-------------|
| **HC** | Headcount — quantidade e gestão de colaboradores |
| **FC** | Fulfillment Center — centro de distribuição |
| **AA** | Associate Ambassador — operador de chão de fábrica |
| **PIT** | Process Improvement Technician — técnico de melhoria de processos |
| **LC** | Learning Curve — nível de capacitação por processo |
| **VTO** | Voluntary Time Off — ausência voluntária solicitada pelo colaborador |
| **VTE** | Voluntary Time Extension — extensão voluntária em outro setor/turno |
| **LS** | Labor Share — compartilhamento temporário de HC entre setores |
| **LT** | Labor Transfer — transferência definitiva de HC |
| **TOFF** | Turn Off — redução de HC (desligamento programado) |
| **RP** | Ramp Down — redução programada de capacidade |
| **ON** | New Hire — contratação de novo colaborador |
| **RME** | Reliability Maintenance Engineering — área de manutenção e engenharia |
| **EXPERT** | Nível máximo de acesso no sistema |
| **OFF** | Status de colaborador com pendência vencida sem data definida |

---

## 17. Suporte e Contato

- Problemas de acesso: solicite ao **EXPERT** da sua operação
- Dúvidas sobre tickets de premissas: consulte o time de **Planejamento / RME**
- Dúvidas sobre VTO/VTE: consulte o time de **RH**
- Problemas técnicos no sistema: acione o time de **TI / Desenvolvimento**

---

*Documento gerado automaticamente a partir da base de código do HC Overview.*
*Última atualização: Agosto/2026*
