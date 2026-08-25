from datetime import date, timedelta

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


class Ticket(db.Model):
    """Mapeia a tabela 'tickets' ja existente no Railway (criada e mantida por uma
    ferramenta externa que espelha 'gig2_hc_premises'). O HC Overview so LE essas
    colunas e ESCREVE apenas nas colunas proprias hcview_* (ver migracao em app.py) -
    nunca cria nem recria essa tabela (ver _create_operational_tables_for_fc em app.py).
    Declara somente as colunas que o HC Overview usa; as demais colunas da tabela real
    (data, hora, premissa, qtd, premise_amount_snapshot, application_mode...) sao
    mantidas pela ferramenta externa e nao precisam estar mapeadas aqui.
    """

    __tablename__ = "tickets"
    __table_args__ = {"extend_existing": True}

    premise_id = db.Column(db.Integer, primary_key=True)
    premise_type = db.Column(db.String(20))
    premise_name = db.Column(db.String(100))
    premise_status = db.Column(db.String(20))

    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    work_date = db.Column(db.Date)

    sector_key = db.Column(db.String(100))
    process_name = db.Column(db.String(100))
    labor_type = db.Column(db.String(50))
    shift_key = db.Column(db.String(50))
    shift_name = db.Column(db.String(50))

    source_sector_key = db.Column(db.String(100))
    source_labor_type = db.Column(db.String(50))
    source_work_date = db.Column(db.Date)
    source_shift_key = db.Column(db.String(50))
    source_shift_name = db.Column(db.String(50))

    repeat_forward = db.Column(db.Boolean)
    amount = db.Column(db.Integer)
    premise_note_snapshot = db.Column(db.Text)

    created_by = db.Column(db.String(100))
    responsible_name = db.Column(db.String(150))
    responsible_login = db.Column(db.String(50))
    source_responsible_name = db.Column(db.String(150))
    source_responsible_login = db.Column(db.String(50))

    created_at = db.Column(db.DateTime)
    updated_at = db.Column(db.DateTime)

    # ── Colunas proprias do HC Overview (migradas em app.py) ────────
    # A ferramenta externa so faz INSERT/UPDATE das colunas acima (ver upsert com
    # lista explicita de colunas) - estas ficam de fora do upsert dela e sao seguras
    # para o HC Overview controlar sozinho.
    hcview_resolvido = db.Column(db.Boolean, default=False)
    hcview_resolvido_em = db.Column(db.DateTime)
    hcview_resolvido_por_login = db.Column(db.String(50))
    hcview_resolvido_por_nome = db.Column(db.String(150))

    # ── Regras de negocio ────────────────────────────────────────────

    @property
    def tipo_label(self):
        return self.premise_name or TICKET_TYPE_LABELS.get(self.premise_type, self.premise_type or "")

    @property
    def is_transferencia(self):
        return self.premise_type in TICKET_TRANSFER_TYPES

    @property
    def owner_login(self):
        """Quem precisa agir no List para resolver o ticket.
        LS/LT/LM: quem libera o HC (lado origem). TOFF/RP: quem reduz o proprio setor.
        ON: sem owner - so aparece para nivel EXPERT."""
        if self.premise_type == "ON":
            return None
        if self.is_transferencia:
            return self.source_responsible_login
        return self.responsible_login

    @property
    def owner_nome(self):
        if self.premise_type == "ON":
            return None
        if self.is_transferencia:
            return self.source_responsible_name
        return self.responsible_name

    @property
    def prazo(self):
        """Prazo = 3 dias antes da data solicitada (work_date)."""
        if not self.work_date:
            return None
        return self.work_date - timedelta(days=PRAZO_DIAS_ANTES)

    @property
    def vencido(self):
        prazo = self.prazo
        return bool(prazo) and date.today() > prazo

    @property
    def nao_conforme(self):
        return self.vencido and not self.hcview_resolvido and self.premise_status != "FINALIZADA"

    def to_dict(self):
        return {
            "premise_id": self.premise_id,
            "premise_type": self.premise_type,
            "tipo_label": self.tipo_label,
            "premise_status": self.premise_status or "",
            "is_transferencia": self.is_transferencia,
            "sector_key": self.sector_key or "",
            "process_name": self.process_name or "",
            "labor_type": self.labor_type or "",
            "shift_key": self.shift_key or "",
            "shift_name": self.shift_name or "",
            "source_sector_key": self.source_sector_key or "",
            "source_labor_type": self.source_labor_type or "",
            "source_shift_key": self.source_shift_key or "",
            "source_shift_name": self.source_shift_name or "",
            "amount": self.amount or 0,
            "responsible_name": self.responsible_name or "",
            "responsible_login": self.responsible_login or "",
            "source_responsible_name": self.source_responsible_name or "",
            "source_responsible_login": self.source_responsible_login or "",
            "owner_login": self.owner_login or "",
            "owner_nome": self.owner_nome or "",
            "work_date": self.work_date.strftime("%Y-%m-%d") if self.work_date else None,
            "end_date": self.end_date.strftime("%Y-%m-%d") if self.end_date else None,
            "prazo": self.prazo.strftime("%Y-%m-%d") if self.prazo else None,
            "vencido": self.vencido,
            "nao_conforme": self.nao_conforme,
            "resolvido": bool(self.hcview_resolvido),
            "resolvido_em": self.hcview_resolvido_em.strftime("%Y-%m-%d %H:%M:%S") if self.hcview_resolvido_em else None,
            "resolvido_por_nome": self.hcview_resolvido_por_nome or "",
            "nota": self.premise_note_snapshot or "",
        }
