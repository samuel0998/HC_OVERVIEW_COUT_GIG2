from datetime import datetime

from models import db

# Tipos suportados pelo HC Overview nesta tabela
CLAIM_TYPES = ("VTO", "VTE", "HORA_EXTRA")
CLAIM_TYPE_LABELS = {
    "VTO": "VTO (Voluntary Time Off)",
    "VTE": "VTE (Voluntary Time Extension)",
    "HORA_EXTRA": "Hora Extra",
}


class PortalTicketClaim(db.Model):
    """Mapeia a tabela 'portal_ticket_claims' já existente no Railway (ferramenta externa).
    O HC Overview só LÊ as colunas originais e ESCREVE apenas nas colunas hcview_*,
    nunca recria nem altera a estrutura original da tabela.
    """

    __tablename__ = "portal_ticket_claims"
    __table_args__ = {"extend_existing": True}

    id = db.Column(db.Integer, primary_key=True)
    labor_ticket_id = db.Column(db.Integer)
    premise_id = db.Column(db.Integer)
    associado_id = db.Column(db.Integer)
    status = db.Column(db.String(50))
    premise_type = db.Column(db.String(20))   # VTO | VTE | HORA_EXTRA
    sector_key = db.Column(db.String(100))
    process_name = db.Column(db.String(100))
    labor_type = db.Column(db.String(50))
    work_date = db.Column(db.Date)
    shift_key = db.Column(db.String(50))
    shift_name = db.Column(db.String(50))
    premise_amount_snapshot = db.Column(db.Integer)
    premise_note_snapshot = db.Column(db.Text)
    created_at = db.Column(db.DateTime)
    cancelled_at = db.Column(db.DateTime)

    # ── Colunas próprias do HC Overview (adicionadas via migração) ──
    hcview_resolvido = db.Column(db.Boolean, default=False)
    hcview_resolvido_em = db.Column(db.DateTime)
    hcview_resolvido_por_login = db.Column(db.String(50))
    hcview_resolvido_por_nome = db.Column(db.String(150))
    hcview_observacao = db.Column(db.Text)
    # VTE: guarda área/turno de origem para reversão automática após 12h
    hcview_area_origem = db.Column(db.String(50))
    hcview_turno_origem = db.Column(db.String(50))
    hcview_vte_revertido = db.Column(db.Boolean, default=False)

    # ── Propriedades de negócio ──────────────────────────────────────

    @property
    def tipo_label(self):
        return CLAIM_TYPE_LABELS.get(self.premise_type or "", self.premise_type or "")

    @property
    def pendente(self):
        """Ticket ativo: não cancelado e não resolvido pelo HC Overview."""
        if self.cancelled_at:
            return False
        if self.hcview_resolvido:
            return False
        return (self.status or "").lower() == "ativo"

    def to_dict(self):
        return {
            "id": self.id,
            "labor_ticket_id": self.labor_ticket_id,
            "premise_id": self.premise_id,
            "associado_id": self.associado_id,
            "status": self.status or "",
            "premise_type": self.premise_type or "",
            "tipo_label": self.tipo_label,
            "sector_key": self.sector_key or "",
            "process_name": self.process_name or "",
            "labor_type": self.labor_type or "",
            "work_date": self.work_date.strftime("%Y-%m-%d") if self.work_date else None,
            "shift_key": self.shift_key or "",
            "shift_name": self.shift_name or "",
            "premise_amount_snapshot": self.premise_amount_snapshot or 0,
            "premise_note_snapshot": self.premise_note_snapshot or "",
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "cancelled_at": self.cancelled_at.strftime("%Y-%m-%d %H:%M:%S") if self.cancelled_at else None,
            "resolvido": bool(self.hcview_resolvido),
            "resolvido_em": self.hcview_resolvido_em.strftime("%Y-%m-%d %H:%M:%S") if self.hcview_resolvido_em else None,
            "resolvido_por_login": self.hcview_resolvido_por_login or "",
            "resolvido_por_nome": self.hcview_resolvido_por_nome or "",
            "observacao": self.hcview_observacao or "",
            "area_origem": self.hcview_area_origem or "",
            "turno_origem": self.hcview_turno_origem or "",
            "vte_revertido": bool(self.hcview_vte_revertido),
        }
