from datetime import datetime

from models import db


class HistoricoOperacional(db.Model):
    __tablename__ = "historico_operacional"

    id = db.Column(db.Integer, primary_key=True)
    hc_id_original = db.Column(db.Integer, nullable=True)
    nome_completo = db.Column(db.String(150), nullable=False)
    login = db.Column(db.String(50), nullable=True)
    cargo = db.Column(db.String(50), nullable=True)
    area = db.Column(db.String(50), nullable=True)
    turno = db.Column(db.String(50), nullable=True)
    status_final = db.Column(db.String(20), nullable=True)
    data_desligamento = db.Column(db.Date, nullable=True)
    data_inicio_licenca = db.Column(db.Date, nullable=True)
    data_fim_licenca = db.Column(db.Date, nullable=True)
    causa = db.Column(db.String(500), nullable=True)
    data_criacao_original = db.Column(db.DateTime, nullable=True)
    data_arquivo = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    arquivado_por = db.Column(db.String(50), nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "hc_id_original": self.hc_id_original,
            "nome_completo": self.nome_completo,
            "login": self.login or "",
            "cargo": self.cargo or "",
            "area": self.area or "",
            "turno": self.turno or "",
            "status_final": self.status_final or "",
            "data_desligamento": self.data_desligamento.strftime("%d/%m/%Y") if self.data_desligamento else None,
            "data_inicio_licenca": self.data_inicio_licenca.strftime("%d/%m/%Y") if self.data_inicio_licenca else None,
            "data_fim_licenca": self.data_fim_licenca.strftime("%d/%m/%Y") if self.data_fim_licenca else None,
            "causa": self.causa or "",
            "data_criacao_original": self.data_criacao_original.strftime("%Y-%m-%d %H:%M:%S") if self.data_criacao_original else None,
            "data_arquivo": self.data_arquivo.strftime("%d/%m/%Y %H:%M") if self.data_arquivo else None,
            "arquivado_por": self.arquivado_por or "",
        }
