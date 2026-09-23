import unicodedata
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from models import db


class HCGig2(db.Model):
    __tablename__ = "hc_gig2"

    id = db.Column(db.Integer, primary_key=True)
    nome_completo = db.Column(db.String(150), nullable=False)
    login = db.Column(db.String(50), unique=True, nullable=True, index=True)
    cargo = db.Column(db.String(50), nullable=False, index=True)
    # Rótulo puramente visual: marca um PIT selecionado como "PIT Trainee" no
    # cadastro/edição (ver _cargo_normalizado/_formatar_cargo em routes/hc.py).
    # O campo cargo acima continua gravado como "PIT" sempre - capacidade,
    # tickets e as demais ferramentas seguem contando normalmente como PIT.
    # Só controla o que aparece no LIST e no Dashboard (ver to_dict abaixo).
    pit_trainee = db.Column(db.Boolean, nullable=False, default=False)
    area = db.Column(db.String(50), nullable=True, index=True)
    turno = db.Column(db.String(50), nullable=True, index=True)
    status = db.Column(db.String(20), nullable=False, default="OPERACIONAL", index=True)
    presente_fc = db.Column(db.Boolean, nullable=False, default=True, index=True)
    presenca_manual = db.Column(db.Boolean, nullable=False, default=False)
    job = db.Column(db.String(80), nullable=True, index=True)
    hora_extra_turno = db.Column(db.String(50), nullable=True, index=True)
    status_liberacao = db.Column(db.String(100), nullable=True)
    # Status agendado: guarda "Licença" | "Férias" | "Desligado" quando a data marcada
    # ainda não chegou. O status atual (acima) só muda para esse valor quando a data vira.
    status_agendado = db.Column(db.String(20), nullable=True)
    # Guarda "Licença" | "Férias" | "Desligado" quando o status atual virou OFF por
    # pendência de data vencida (prazo de terça). Enquanto preenchido, o colaborador
    # continua aparecendo em Pendências mesmo já estando OFF — o prazo é só alerta visual.
    off_origem = db.Column(db.String(20), nullable=True)
    # Licença / Férias
    data_inicio_licenca = db.Column(db.Date, nullable=True)
    data_fim_licenca = db.Column(db.Date, nullable=True)
    # Desligamento
    data_desligamento = db.Column(db.Date, nullable=True)
    # Ausência: status de 24h que tira o colaborador da capacidade operacional só no
    # dia marcado. A partir do dia seguinte, a rotina de status automático devolve
    # para OPERACIONAL (ver aplicar_status_por_data e processar_status_automatico).
    data_inicio_ausencia = db.Column(db.Date, nullable=True)
    # VTE/VTO: status temporarios criados exclusivamente por tickets de RH.
    status_temporario_inicio = db.Column(db.DateTime, nullable=True)
    status_temporario_fim = db.Column(db.DateTime, nullable=True)
    vte_area_origem = db.Column(db.String(50), nullable=True)
    vte_turno_origem = db.Column(db.String(50), nullable=True)
    vte_area_destino = db.Column(db.String(50), nullable=True)
    vte_turno_destino = db.Column(db.String(50), nullable=True)
    # Labor Share: retorna para a alocacao de origem na data final do ticket.
    ls_retorno_data = db.Column(db.Date, nullable=True)
    # Momento efetivo do retorno. Mantem-se a data separada para auditoria e para
    # conferir o pedido do ticket; quando o LS e' aberto para o mesmo dia, este
    # campo recebe agora + 24h.
    ls_retorno_em = db.Column(db.DateTime, nullable=True)
    ls_area_origem = db.Column(db.String(50), nullable=True)
    ls_turno_origem = db.Column(db.String(50), nullable=True)
    ls_ticket_id = db.Column(db.Integer, nullable=True)
    # Treinamento: data em que o ciclo ATUAL de Treinamento comecou. Usada para
    # contar os dias de treinamento em vez de created_at, pois um colaborador
    # antigo pode ser recolocado em Treinamento manualmente muito depois do
    # cadastro original (ver aplicar_status_por_data). Sem valor (registros
    # legados / cadastro novo antes desta coluna existir), cai no created_at.
    treinamento_inicio_em = db.Column(db.Date, nullable=True)
    # Transferencia definitiva entre sites-irmaos (ex.: CNF2 <-> IXD - CNF2).
    # Guarda o label do site de origem enquanto o colaborador chega sem setor
    # definido no banco de destino; fica visivel em Pendencias ate alguem
    # preencher a area (ver _pendencia_filtro / atualizar_colaborador).
    pendente_transferencia_origem = db.Column(db.String(30), nullable=True)
    # Campos legados mantidos para compatibilidade
    previsao_afastamento = db.Column(db.Boolean, nullable=False, default=False)
    data_afastamento = db.Column(db.Date, nullable=True)
    causa_afastamento = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def cargo_exibicao(self):
        """Cargo como deve aparecer no LIST/Dashboard: "PIT Trainee" quando
        marcado como tal (pit_trainee), senão o cargo gravado normalmente. O
        campo cargo em si nunca muda - ver comentário na coluna pit_trainee."""
        if self.cargo == "PIT" and self.pit_trainee:
            return "PIT Trainee"
        return self.cargo

    def _status_afastamento_ativo(self):
        return self.status in ("Licença", "Férias")

    def _cargo_normalizado(self):
        return unicodedata.normalize("NFKD", self.cargo or "").encode("ascii", "ignore").decode("ascii").upper().strip()

    def _dias_desde_cadastro(self, hoje):
        data_cadastro = self.created_at.date() if self.created_at else hoje
        return (hoje - data_cadastro).days

    def _dias_desde_inicio_treinamento(self, hoje):
        """Dias desde que o ciclo ATUAL de Treinamento comecou. Prioriza
        treinamento_inicio_em (setado sempre que o status vira Treinamento de
        novo, seja no cadastro ou numa edicao manual); sem essa data, cai no
        created_at para nao quebrar registros legados."""
        base = self.treinamento_inicio_em or (self.created_at.date() if self.created_at else hoje)
        return (hoje - base).days

    def limpar_bloqueios_afastamento(self):
        anterior = (
            self.data_inicio_licenca,
            self.data_fim_licenca,
            self.previsao_afastamento,
            self.data_afastamento,
            self.causa_afastamento,
            self.status_agendado,
            self.off_origem,
        )
        self.data_inicio_licenca = None
        self.data_fim_licenca = None
        self.previsao_afastamento = False
        self.data_afastamento = None
        self.causa_afastamento = None
        self.status_agendado = None
        self.off_origem = None
        return anterior != (
            self.data_inicio_licenca,
            self.data_fim_licenca,
            self.previsao_afastamento,
            self.data_afastamento,
            self.causa_afastamento,
            self.status_agendado,
            self.off_origem,
        )

    def limpar_status_temporario(self):
        anterior = (
            self.status_temporario_inicio,
            self.status_temporario_fim,
            self.vte_area_origem,
            self.vte_turno_origem,
            self.vte_area_destino,
            self.vte_turno_destino,
        )
        self.status_temporario_inicio = None
        self.status_temporario_fim = None
        self.vte_area_origem = None
        self.vte_turno_origem = None
        self.vte_area_destino = None
        self.vte_turno_destino = None
        return any(valor is not None for valor in anterior)

    def _ativar_status_agendado(self, hoje, agora):
        """Ativa afastamentos ou VTE/VTO quando a data agendada chega."""
        if not self.status_agendado:
            return False

        if self.status_agendado in ("Licença", "Férias"):
            if self.data_inicio_licenca and hoje >= self.data_inicio_licenca:
                self.status = self.status_agendado
                self.status_agendado = None
                return True
        elif self.status_agendado == "Desligado":
            if self.data_desligamento and hoje >= self.data_desligamento:
                self.status = "Desligado"
                self.status_agendado = None
                return True
        elif self.status_agendado in ("VTE", "VTO"):
            if self.status_temporario_inicio and agora >= self.status_temporario_inicio:
                self.status = self.status_agendado
                self.status_agendado = None
                self.status_temporario_fim = self.status_temporario_inicio + timedelta(hours=12)
                if self.status == "VTE":
                    self.area = self.vte_area_destino or self.area
                    self.turno = self.vte_turno_destino or self.turno
                return True

        return False

    def limpar_retorno_ls(self):
        self.ls_retorno_data = None
        self.ls_retorno_em = None
        self.ls_area_origem = None
        self.ls_turno_origem = None
        self.ls_ticket_id = None

    def aplicar_status_por_data(self, hoje=None, agora=None):
        hoje = hoje or datetime.now(ZoneInfo("America/Sao_Paulo")).date()
        agora = agora or datetime.utcnow()
        status_anterior = self.status
        alocacao_anterior = (self.area, self.turno)

        alterou_bloqueios = False
        self._ativar_status_agendado(hoje, agora)

        retorno_ls_chegou = (
            self.ls_retorno_em is not None and agora >= self.ls_retorno_em
        ) or (
            self.ls_retorno_em is None
            and self.ls_retorno_data is not None
            and hoje >= self.ls_retorno_data
        )
        if retorno_ls_chegou:
            self.area = self.ls_area_origem or self.area
            self.turno = self.ls_turno_origem or self.turno
            self.limpar_retorno_ls()
            if self.status == "LS":
                self.status = "OPERACIONAL"
            alterou_bloqueios = True

        if self.status in ("VTE", "VTO") and self.status_temporario_fim and agora >= self.status_temporario_fim:
            if self.status == "VTE":
                self.area = self.vte_area_origem or self.area
                self.turno = self.vte_turno_origem or self.turno
            self.status = "OPERACIONAL"
            alterou_bloqueios = self.limpar_status_temporario() or alterou_bloqueios

        if self.status == "Treinamento":
            cargo = self._cargo_normalizado()
            dias = self._dias_desde_inicio_treinamento(hoje)
            if cargo in ("AA", "ASSOCIADO") and dias >= 2:
                self.status = "OPERACIONAL"
                self.treinamento_inicio_em = None
            elif cargo == "PIT" and dias >= 5:
                self.status = "OPERACIONAL"
                self.treinamento_inicio_em = None
        elif self.status in ("Ausência", "Ausencia"):
            # Ausência vale só pelo dia marcado (24h). Sem data registrada, assume hoje.
            # A partir do dia seguinte, volta automaticamente para OPERACIONAL.
            if not self.data_inicio_ausencia:
                self.data_inicio_ausencia = hoje
            elif hoje > self.data_inicio_ausencia:
                self.status = "OPERACIONAL"
                self.data_inicio_ausencia = None
        elif self._status_afastamento_ativo():
            if self.data_inicio_licenca and hoje < self.data_inicio_licenca:
                # Registro legado: o status foi gravado direto (regra antiga) antes da
                # data de início chegar. Autocorrige para o modelo de status agendado,
                # sem perder data/causa já cadastradas.
                self.status_agendado = self.status
                self.status = "OPERACIONAL"
            elif self.data_fim_licenca and hoje >= self.data_fim_licenca:
                self.status = "OPERACIONAL"
                alterou_bloqueios = self.limpar_bloqueios_afastamento()
        elif self.status == "Desligado" and self.data_desligamento and hoje < self.data_desligamento:
            # Mesmo caso acima, mas para desligamento gravado antes da hora.
            self.status_agendado = "Desligado"
            self.status = "OPERACIONAL"
        elif self.status == "OPERACIONAL":
            # Nao limpa datas/causa se houver uma Ferias/Licenca/Desligamento agendado
            # para o futuro aguardando a data chegar (ver _ativar_status_agendado).
            if not self.status_agendado:
                alterou_bloqueios = self.limpar_bloqueios_afastamento()
            self.data_inicio_ausencia = None
        elif self.status == "Desligado":
            pass  # Desligado não reverte automaticamente

        return status_anterior != self.status or alocacao_anterior != (self.area, self.turno) or alterou_bloqueios

    def to_dict(self):
        return {
            "id": self.id,
            "nome_completo": self.nome_completo,
            "login": self.login or "",
            "cargo": self.cargo,
            "pit_trainee": bool(self.pit_trainee),
            "cargo_exibicao": self.cargo_exibicao(),
            "area": self.area or "",
            "turno": self.turno or "",
            "status": self.status,
            "status_agendado": self.status_agendado or "",
            "off_origem": self.off_origem or "",
            "treinamento_inicio_em": self.treinamento_inicio_em.strftime("%Y-%m-%d") if self.treinamento_inicio_em else None,
            "pendente_transferencia_origem": self.pendente_transferencia_origem or "",
            "presente_fc": bool(self.presente_fc),
            "job": self.job or "",
            "hora_extra_turno": self.hora_extra_turno or "",
            "status_liberacao": self.status_liberacao or "",
            "data_inicio_licenca": self.data_inicio_licenca.strftime("%Y-%m-%d") if self.data_inicio_licenca else None,
            "data_fim_licenca": self.data_fim_licenca.strftime("%Y-%m-%d") if self.data_fim_licenca else None,
            "data_desligamento": self.data_desligamento.strftime("%Y-%m-%d") if self.data_desligamento else None,
            "data_inicio_ausencia": self.data_inicio_ausencia.strftime("%Y-%m-%d") if self.data_inicio_ausencia else None,
            "status_temporario_inicio": self.status_temporario_inicio.strftime("%Y-%m-%dT%H:%M") if self.status_temporario_inicio else None,
            "status_temporario_fim": self.status_temporario_fim.strftime("%Y-%m-%dT%H:%M") if self.status_temporario_fim else None,
            "vte_area_origem": self.vte_area_origem or "",
            "vte_turno_origem": self.vte_turno_origem or "",
            "vte_area_destino": self.vte_area_destino or "",
            "vte_turno_destino": self.vte_turno_destino or "",
            "ls_retorno_data": self.ls_retorno_data.strftime("%Y-%m-%d") if self.ls_retorno_data else None,
            "ls_retorno_em": (
                self.ls_retorno_em.replace(tzinfo=ZoneInfo("UTC"))
                .astimezone(ZoneInfo("America/Sao_Paulo"))
                .strftime("%Y-%m-%dT%H:%M")
                if self.ls_retorno_em else None
            ),
            "ls_area_origem": self.ls_area_origem or "",
            "ls_turno_origem": self.ls_turno_origem or "",
            "ls_ticket_id": self.ls_ticket_id,
            "previsao_afastamento": self.previsao_afastamento,
            "data_afastamento": self.data_afastamento.strftime("%Y-%m-%d") if self.data_afastamento else None,
            "causa_afastamento": self.causa_afastamento or "",
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }
