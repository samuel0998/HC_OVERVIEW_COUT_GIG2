from datetime import date, datetime
from models import db


class HCGig2(db.Model):
    __tablename__ = "hc_gig2"

    id = db.Column(db.Integer, primary_key=True)
    nome_completo = db.Column(db.String(150), nullable=False)
    login = db.Column(db.String(50), unique=True, nullable=False, index=True)
    cargo = db.Column(db.String(50), nullable=False, index=True)
    area = db.Column(db.String(50), nullable=False, index=True)
    turno = db.Column(db.String(50), nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default="OPERACIONAL", index=True)
    previsao_afastamento = db.Column(db.Boolean, nullable=False, default=False)
    data_afastamento = db.Column(db.Date, nullable=True)
    causa_afastamento = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def aplicar_status_por_data(self):
        if self.previsao_afastamento and self.data_afastamento and self.data_afastamento <= date.today():
            self.status = "OFF"
        elif self.status not in ["OFF", "OPERACIONAL"]:
            self.status = "OPERACIONAL"

    def to_dict(self):
        self.aplicar_status_por_data()
        return {
            "id": self.id,
            "nome_completo": self.nome_completo,
            "login": self.login,
            "cargo": self.cargo,
            "area": self.area,
            "turno": self.turno,
            "status": self.status,
            "previsao_afastamento": self.previsao_afastamento,
            "data_afastamento": self.data_afastamento.strftime("%Y-%m-%d") if self.data_afastamento else None,
            "causa_afastamento": self.causa_afastamento,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }
