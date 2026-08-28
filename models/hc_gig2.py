import unicodedata
from datetime import date, datetime
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

    def _ativar_status_agendado(self, hoje):
        """Vira Licença/Férias/Desligado somente quando a data marcada chega."""
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

        return False

    def aplicar_status_por_data(self, hoje=None):
        hoje = hoje or date.today()
        status_anterior = self.status

        alterou_bloqueios = False
        self._ativar_status_agendado(hoje)

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

        return status_anterior != self.status or alterou_bloqueios

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
            "previsao_afastamento": self.previsao_afastamento,
            "data_afastamento": self.data_afastamento.strftime("%Y-%m-%d") if self.data_afastamento else None,
            "causa_afastamento": self.causa_afastamento or "",
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }
