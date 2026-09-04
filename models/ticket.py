from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from models import db

# Tipos de premissa que o HC Overview acompanha em Pendencias.
# LM e um alias legado de LT (ver mapeamento na ferramenta externa que popula 'tickets').
TICKET_TYPES = ("LS", "LT", "LM", "TOFF", "RP", "ON")
TICKET_TRANSFER_TYPES = ("LS", "LT", "LM")

TICKET_TYPE_LABELS = {
    "LS": "Labor Share (LS)",
    "LT": "Labor Transfer (LT)",
    "LM": "Labor Transfer (LT)",
    "TOFF": "Turn Off (TOFF)",
    "RP": "Ramp Down (RP)",
    "ON": "New Hire (ON)",
}

PRAZO_DIAS_ANTES = 3
FUSO_OPERACAO = ZoneInfo("America/Sao_Paulo")


def _escala_turno(escala, turno):
    """Junta os campos separados do ticket (escala='BLUE', turno='Day') no mesmo
    formato usado pelo campo `turno` do HC ('BLUE DAY'). Vazio se nada informado."""
    partes = [str(p).strip() for p in (escala, turno) if p and str(p).strip()]
    return " ".join(partes).upper()


def _primeiro(*valores):
    for v in valores:
        if v is not None and str(v).strip() != "":
            return v
    return ""


class Ticket(db.Model):
    """Mapeia a tabela 'tickets' ja existente no Railway (criada e mantida por uma
    ferramenta externa que espelha 'gig2_hc_premises'). O HC Overview so LE essas
    colunas e ESCREVE apenas nas colunas proprias hcview_* (ver migracao em app.py) -
    nunca cria nem recria essa tabela (ver _create_operational_tables_for_fc em app.py).

    A tabela tem DOIS conjuntos de colunas de setor/escala/turno vivendo lado a lado
    (schema real conferido pelo usuario 2026-09-01):
      - legado combinado: sector_key / shift_name / source_sector_key / source_shift_name
      - novo detalhado:   setor / escala / turno / setor_origem / escala_origem / turno_origem
    Os acessores sector_key / source_sector_key / shift_name / source_shift_name viraram
    @property que usam o conjunto NOVO e caem no legado quando o novo esta vazio, para
    funcionar independente de qual a ferramenta preenche.
    """

    __tablename__ = "tickets"
    __table_args__ = {"extend_existing": True}

    # PK: a tabela tem `id` (serial) E `premise_id`. Mantido `premise_id` como PK
    # porque e' o que o endpoint /resolver e o front usam. SE `premise_id` repetir
    # (1 linha por pessoa), isso precisa virar `id` + ajustar resolver_ticket.
    premise_id = db.Column(db.Integer, primary_key=True)
    associado_id = db.Column(db.Integer)

    premise_type = db.Column(db.String(20))
    premise_name = db.Column(db.String(100))
    premise_status = db.Column(db.String(20))

    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    work_date = db.Column(db.Date)
    source_work_date = db.Column(db.Date)

    # ── Setor / escala / turno: conjunto NOVO (detalhado) ──────────
    setor = db.Column(db.String(100))            # destino
    escala = db.Column(db.String(20))            # destino: BLUE / RED
    turno = db.Column(db.String(20))             # destino: Day / Night
    setor_origem = db.Column(db.String(100))
    escala_origem = db.Column(db.String(20))
    turno_origem = db.Column(db.String(20))
    area = db.Column(db.String(100))             # area atual do colaborador

    # ── Setor / escala / turno: conjunto LEGADO (combinado) ────────
    _sector_key = db.Column("sector_key", db.String(100))
    _shift_key = db.Column("shift_key", db.String(50))
    _shift_name = db.Column("shift_name", db.String(50))
    _source_sector_key = db.Column("source_sector_key", db.String(100))
    _source_shift_key = db.Column("source_shift_key", db.String(50))
    _source_shift_name = db.Column("source_shift_name", db.String(50))

    process_name = db.Column(db.String(100))
    _labor_type = db.Column("labor_type", db.String(50))
    _source_labor_type = db.Column("source_labor_type", db.String(50))
    cargo = db.Column(db.String(50))             # cargo do colaborador (novo)
    colaborador = db.Column(db.String(150))
    login = db.Column(db.String(50))

    repeat_forward = db.Column(db.Boolean)
    _amount = db.Column("amount", db.Integer)
    qtd = db.Column(db.Integer)
    premise_note_snapshot = db.Column(db.Text)

    created_by = db.Column(db.String(100))
    responsible_name = db.Column(db.String(150))
    responsible_login = db.Column(db.String(50))
    source_responsible_name = db.Column(db.String(150))
    source_responsible_login = db.Column(db.String(50))

    created_at = db.Column(db.DateTime)
    updated_at = db.Column(db.DateTime)
    labor_validado_at = db.Column(db.DateTime)

    # ── Colunas proprias do HC Overview (migradas em app.py) ────────
    hcview_resolvido = db.Column(db.Boolean, default=False)
    hcview_resolvido_em = db.Column(db.DateTime)
    hcview_resolvido_at = db.Column(db.DateTime)
    hcview_resolvido_por_login = db.Column(db.String(50))
    hcview_resolvido_por_nome = db.Column(db.String(150))

    # Gestao pelo time de Planning (LC-HARD-EXPERT):
    #   arquivado -> some das Pendencias do owner; EXPERT ve so' leitura; nao valida.
    #   cancelado -> some pra todo mundo (equivale a excluir o ticket).
    hcview_arquivado = db.Column(db.Boolean, default=False)
    hcview_arquivado_por = db.Column(db.String(50))
    hcview_arquivado_em = db.Column(db.DateTime)
    hcview_cancelado = db.Column(db.Boolean, default=False)
    hcview_cancelado_por = db.Column(db.String(50))
    hcview_cancelado_em = db.Column(db.DateTime)

    # ── Acessores: novo -> legado ─────────────────────────────────
    @property
    def sector_key(self):
        return _primeiro(self.setor, self._sector_key)

    @property
    def source_sector_key(self):
        return _primeiro(self.setor_origem, self._source_sector_key)

    @property
    def shift_name(self):
        """Escala+turno do destino no formato do HC ('BLUE DAY')."""
        return _primeiro(_escala_turno(self.escala, self.turno), self._shift_name)

    @property
    def source_shift_name(self):
        """Escala+turno da origem no formato do HC ('BLUE DAY')."""
        return _primeiro(_escala_turno(self.escala_origem, self.turno_origem), self._source_shift_name)

    @property
    def shift_key(self):
        return self._shift_key or ""

    @property
    def source_shift_key(self):
        return self._source_shift_key or ""

    @property
    def labor_type(self):
        return _primeiro(self._labor_type, self.cargo)

    @property
    def source_labor_type(self):
        return _primeiro(self._source_labor_type, self.cargo)

    @property
    def amount(self):
        return self._amount or self.qtd or 0

    # ── Regras de negocio ────────────────────────────────────────────

    @property
    def tipo_label(self):
        return self.premise_name or TICKET_TYPE_LABELS.get(self.premise_type, self.premise_type or "")

    @property
    def is_transferencia(self):
        return self.premise_type in TICKET_TRANSFER_TYPES

    @property
    def owner_login(self):
        """Quem precisa agir para resolver o ticket = o responsavel da ORIGEM
        (`source_responsible_login`), com fallback para `responsible_login`.
        Vale para TODAS as premissas, inclusive ON (New Hire)."""
        return self.source_responsible_login or self.responsible_login

    @property
    def owner_nome(self):
        return self.source_responsible_name or self.responsible_name

    @property
    def prazo(self):
        """LS/LT vencem no dia solicitado; demais tipos mantêm a antecedência."""
        if not self.work_date:
            return None
        if (self.premise_type or "").upper() in TICKET_TRANSFER_TYPES:
            return self.work_date
        return self.work_date - timedelta(days=PRAZO_DIAS_ANTES)

    def _turno_chave_prazo(self):
        candidatos = (
            _escala_turno(self.escala, self.turno),
            _escala_turno(self.shift_key, self._shift_name),
            self.shift_name,
        )
        for valor in candidatos:
            chave = " ".join(str(valor or "").upper().replace("-", " ").replace("_", " ").split())
            if chave in ("BLUE DAY", "BLUE NIGHT", "RED DAY", "RED NIGHT", "ADM"):
                return chave
        return ""

    def hora_prazo(self):
        """Horário limite configurado para o shift de destino do LS/LT."""
        if (self.premise_type or "").upper() not in TICKET_TRANSFER_TYPES:
            return ""
        chave = self._turno_chave_prazo()
        try:
            from models.turno_config import DEFAULT_TURNO_RESET, HCTurnoConfig
            config = db.session.get(HCTurnoConfig, chave) if chave else None
            return (config.hora_reset if config else DEFAULT_TURNO_RESET.get(chave)) or "23:59"
        except Exception:
            from models.turno_config import DEFAULT_TURNO_RESET
            return DEFAULT_TURNO_RESET.get(chave, "23:59")

    def prazo_em(self, hora_limite=None):
        if not self.prazo:
            return None
        if (self.premise_type or "").upper() not in TICKET_TRANSFER_TYPES:
            return None
        try:
            hora, minuto = [int(parte) for parte in (hora_limite or self.hora_prazo()).split(":", 1)]
        except (AttributeError, TypeError, ValueError):
            hora, minuto = 23, 59
        return datetime.combine(self.prazo, datetime.min.time()).replace(
            hour=hora, minute=minuto, tzinfo=FUSO_OPERACAO
        )

    def esta_vencido(self, agora=None, hora_limite=None):
        if not self.prazo:
            return False
        agora = agora or datetime.now(FUSO_OPERACAO)
        if agora.tzinfo is None:
            agora = agora.replace(tzinfo=FUSO_OPERACAO)
        if (self.premise_type or "").upper() in TICKET_TRANSFER_TYPES:
            return agora > self.prazo_em(hora_limite)
        return agora.astimezone(FUSO_OPERACAO).date() > self.prazo

    @property
    def vencido(self):
        return self.esta_vencido()

    @property
    def nao_conforme(self):
        return self.vencido and not self.hcview_resolvido and self.premise_status != "FINALIZADA"

    def to_dict(self):
        prazo_hora = self.hora_prazo()
        prazo_em = self.prazo_em(prazo_hora or None)
        vencido = self.esta_vencido(hora_limite=prazo_hora or None)
        nao_conforme = vencido and not self.hcview_resolvido and self.premise_status != "FINALIZADA"
        return {
            "premise_id": self.premise_id,
            "premise_type": self.premise_type,
            "tipo_label": self.tipo_label,
            "premise_status": self.premise_status or "",
            "is_transferencia": self.is_transferencia,
            "sector_key": self.sector_key or "",
            "process_name": self.process_name or "",
            "labor_type": self.labor_type or "",
            "escala": self.escala or "",
            "turno": self.turno or "",
            "shift_key": self.shift_key or "",
            "shift_name": self.shift_name or "",
            "source_sector_key": self.source_sector_key or "",
            "source_labor_type": self.source_labor_type or "",
            "escala_origem": self.escala_origem or "",
            "turno_origem": self.turno_origem or "",
            "source_shift_key": self.source_shift_key or "",
            "source_shift_name": self.source_shift_name or "",
            "amount": self.amount or 0,
            "responsible_name": self.responsible_name or "",
            "responsible_login": self.responsible_login or "",
            "source_responsible_name": self.source_responsible_name or "",
            "source_responsible_login": self.source_responsible_login or "",
            "owner_login": self.owner_login or "",
            "owner_nome": self.owner_nome or "",
            "colaborador": self.colaborador or "",
            "colaborador_login": self.login or "",
            "work_date": self.work_date.strftime("%Y-%m-%d") if self.work_date else None,
            "end_date": self.end_date.strftime("%Y-%m-%d") if self.end_date else None,
            "prazo": self.prazo.strftime("%Y-%m-%d") if self.prazo else None,
            "prazo_hora": prazo_hora,
            "prazo_data_hora": prazo_em.strftime("%Y-%m-%d %H:%M") if prazo_em else None,
            "vencido": vencido,
            "nao_conforme": nao_conforme,
            "resolvido": bool(self.hcview_resolvido),
            "resolvido_em": self.hcview_resolvido_em.strftime("%Y-%m-%d %H:%M:%S") if self.hcview_resolvido_em else None,
            "resolvido_por_nome": self.hcview_resolvido_por_nome or "",
            "labor_validado_em": self.labor_validado_at.strftime("%Y-%m-%d %H:%M:%S") if self.labor_validado_at else None,
            "arquivado": bool(self.hcview_arquivado),
            "arquivado_por": self.hcview_arquivado_por or "",
            "arquivado_em": self.hcview_arquivado_em.strftime("%Y-%m-%d %H:%M:%S") if self.hcview_arquivado_em else None,
            "cancelado": bool(self.hcview_cancelado),
            "nota": self.premise_note_snapshot or "",
        }
