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
    status_liberacao = db.Column(db.String(100), nullable=True)
    # Licença / Férias
    data_inicio_licenca = db.Column(db.Date, nullable=True)
    data_fim_licenca = db.Column(db.Date, nullable=True)
    # Desligamento
    data_desligamento = db.Column(db.Date, nullable=True)
    # Campos legados mantidos para compatibilidade
    previsao_afastamento = db.Column(db.Boolean, nullable=False, default=False)
    data_afastamento = db.Column(db.Date, nullable=True)
    causa_afastamento = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "nome_completo": self.nome_completo,
            "login": self.login or "",
            "cargo": self.cargo,
            "area": self.area or "",
            "turno": self.turno or "",
            "status": self.status,
            "status_liberacao": self.status_liberacao or "",
            "data_inicio_licenca": self.data_inicio_licenca.strftime("%Y-%m-%d") if self.data_inicio_licenca else None,
            "data_fim_licenca": self.data_fim_licenca.strftime("%Y-%m-%d") if self.data_fim_licenca else None,
            "data_desligamento": self.data_desligamento.strftime("%Y-%m-%d") if self.data_desligamento else None,
            "previsao_afastamento": self.previsao_afastamento,
            "data_afastamento": self.data_afastamento.strftime("%Y-%m-%d") if self.data_afastamento else None,
            "causa_afastamento": self.causa_afastamento or "",
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }
