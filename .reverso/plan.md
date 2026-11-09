# Plano Reverso: HC Overview (hc_gig2_project)

Modo: fonte · Objetivo: documentar o sistema em specs executáveis (padrão assumido) · Nível: essencial (a confirmar após o Scout)

## Perguntas a responder
- [ ] Q1. Quais entidades e regras de negócio governam o HC (colaborador, turno, LC, ausência, histórico)? → evidência: `models/`, `routes/hc.py`
- [ ] Q2. Como funcionam os tickets de premissa (LS/LT/TOFF/RP/ON) e os ciclos de vida deles? → evidência: `models/ticket.py`, `models/portal_ticket_claims.py`, `routes/hc.py`, testes `test_ticket_*`
- [ ] Q3. Como são autenticação e permissões (login local, central auth, YubiKey, níveis LC)? → evidência: `routes/auth.py`, `routes/central.py`, `models/central_auth.py`, `docs/central_auth_contrato.md`
- [ ] Q4. Quais bancos e integrações externas existem, e como o schema é migrado no boot? → evidência: `app.py`, `config.py`, README (Ariel Planning, IXD - CNF2)
- [ ] Q5. O que o sistema nunca pode quebrar, e onde há dívida técnica ou risco? → evidência: `tests/`, git log, tamanho de `routes/hc.py`

## Fase 1: Reconhecimento
- [ ] **Scout**

## Fase 2: Escavação
- [ ] **Archaeologist**: tarefas por módulo definidas depois do Scout

## Fase 3: Interpretação
- [ ] **Detective**
- [ ] **Architect**

## Fase 4: Geração
- [ ] **Writer**

## Fase 5: Revisão
- [ ] **Reviewer**

## Independentes (opcionais)
- [ ] Data Master · [ ] Design System · [ ] Visor · [ ] Alma (`soul.md`)
