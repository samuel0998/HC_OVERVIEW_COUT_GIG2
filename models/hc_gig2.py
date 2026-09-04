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
    ls_area_origem = db.Column(db.String(50), nullable=True)
    ls_turno_origem = db.Column(db.String(50), nullable=True)
    ls_ticket_id = db.Column(db.Integer, nullable=True)
    # Campos legados mantidos para compatibilidade
    previsao_afastamento = db.Column(db.Boolean, nullable=False, default=False)
    data_afastamento = db.Column(db.Date, nullable=True)
    causa_afastamento = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def _status_afastamento_ativo(self):
        return self.status in ("Licença", "Férias")

    def _cargo_normalizado(self):
        return unicodedata.normalize("NFKD", self.cargo or "").encode("ascii", "ignore").decode("ascii").upper().strip()

    def _dias_desde_cadastro(self, hoje):
        data_cadastro = self.created_at.date() if self.created_at else hoje
        return (hoje - data_cadastro).days

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

        if self.ls_retorno_data and hoje >= self.ls_retorno_data:
            self.area = self.ls_area_origem or self.area
            self.turno = self.ls_turno_origem or self.turno
            self.limpar_retorno_ls()
            alterou_bloqueios = True

        if self.status in ("VTE", "VTO") and self.status_temporario_fim and agora >= self.status_temporario_fim:
            if self.status == "VTE":
                self.area = self.vte_area_origem or self.area
                self.turno = self.vte_turno_origem or self.turno
            self.status = "OPERACIONAL"
            alterou_bloqueios = self.limpar_status_temporario() or alterou_bloqueios

        if self.status == "Treinamento":
            cargo = self._cargo_normalizado()
            dias = self._dias_desde_cadastro(hoje)
            if cargo in ("AA", "ASSOCIADO") and dias >= 2:
                self.status = "OPERACIONAL"
            elif cargo == "PIT" and dias >= 5:
                self.status = "OPERACIONAL"
                self.turno = None
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
            "area": self.area or "",
            "turno": self.turno or "",
            "status": self.status,
            "status_agendado": self.status_agendado or "",
            "off_origem": self.off_origem or "",
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
            "ls_area_origem": self.ls_area_origem or "",
            "ls_turno_origem": self.ls_turno_origem or "",
            "ls_ticket_id": self.ls_ticket_id,
            "previsao_afastamento": self.previsao_afastamento,
            "data_afastamento": self.data_afastamento.strftime("%Y-%m-%d") if self.data_afastamento else None,
            "causa_afastamento": self.causa_afastamento or "",
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }
