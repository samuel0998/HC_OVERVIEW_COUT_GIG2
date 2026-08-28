from datetime import datetime

from models import db


class PortalTicketClaim(db.Model):
    __tablename__ = "portal_ticket_claims"
    __table_args__ = {"extend_existing": True}

    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(10), nullable=False)  # VTO | VTE

    # Solicitante (AA ou PIT que abriu o ticket)
    solicitante_login = db.Column(db.String(50), nullable=False)
    solicitante_nome = db.Column(db.String(150), nullable=False)
    solicitante_cargo = db.Column(db.String(50))
    solicitante_area = db.Column(db.String(50))
    solicitante_turno = db.Column(db.String(50))

    # Dados da solicitação
    data_solicitacao = db.Column(db.Date, nullable=False)       # dia do VTO / início do VTE
    agendado_para = db.Column(db.DateTime, nullable=True)       # VTE: pode ser agendado

    # VTE: setor/turno/escala de destino
    setor_destino = db.Column(db.String(50), nullable=True)
    turno_destino = db.Column(db.String(50), nullable=True)

    # Responsável RME que deve resolver
    rme_responsavel_login = db.Column(db.String(50), nullable=True)
    rme_responsavel_nome = db.Column(db.String(150), nullable=True)

    # Controle de status
    status = db.Column(db.String(20), nullable=False, default="PENDENTE")  # PENDENTE | RESOLVIDO | REJEITADO
    resolvido_em = db.Column(db.DateTime, nullable=True)
    resolvido_por_login = db.Column(db.String(50), nullable=True)
    resolvido_por_nome = db.Column(db.String(150), nullable=True)
    observacao = db.Column(db.Text, nullable=True)

    # VTE: dados originais para reversão automática após 12h
    area_origem = db.Column(db.String(50), nullable=True)
    turno_origem = db.Column(db.String(50), nullable=True)
    vte_revertido = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "tipo": self.tipo,
            "solicitante_login": self.solicitante_login,
            "solicitante_nome": self.solicitante_nome,
            "solicitante_cargo": self.solicitante_cargo or "",
            "solicitante_area": self.solicitante_area or "",
            "solicitante_turno": self.solicitante_turno or "",
            "data_solicitacao": self.data_solicitacao.strftime("%Y-%m-%d") if self.data_solicitacao else None,
            "agendado_para": self.agendado_para.strftime("%Y-%m-%d %H:%M") if self.agendado_para else None,
            "setor_destino": self.setor_destino or "",
            "turno_destino": self.turno_destino or "",
            "rme_responsavel_login": self.rme_responsavel_login or "",
            "rme_responsavel_nome": self.rme_responsavel_nome or "",
            "status": self.status,
            "resolvido_em": self.resolvido_em.strftime("%Y-%m-%d %H:%M:%S") if self.resolvido_em else None,
            "resolvido_por_login": self.resolvido_por_login or "",
            "resolvido_por_nome": self.resolvido_por_nome or "",
            "observacao": self.observacao or "",
            "area_origem": self.area_origem or "",
            "turno_origem": self.turno_origem or "",
            "vte_revertido": bool(self.vte_revertido),
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }
