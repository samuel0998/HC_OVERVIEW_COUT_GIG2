import json
from datetime import datetime

from models import db


class RegistroAtividade(db.Model):
    __tablename__ = "registro_atividade"

    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(50), nullable=False, index=True)
    operador_id = db.Column(db.Integer, nullable=True)
    operador_login = db.Column(db.String(50), nullable=True)
    operador_nome = db.Column(db.String(150), nullable=True)
    usuario_login = db.Column(db.String(50), nullable=True)
    usuario_nome = db.Column(db.String(150), nullable=True)
    descricao = db.Column(db.Text, nullable=True)
    dados_anteriores = db.Column(db.Text, nullable=True)
    dados_novos = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    def to_dict(self):
        try:
            anteriores = json.loads(self.dados_anteriores or "{}")
            anteriores = anteriores if isinstance(anteriores, dict) else {}
        except (TypeError, ValueError):
            anteriores = {}
        try:
            novos = json.loads(self.dados_novos or "{}")
            novos = novos if isinstance(novos, dict) else {}
        except (TypeError, ValueError):
            novos = {}

        campos = (
            ("area", "Setor"),
            ("turno", "Turno/escala"),
            ("cargo", "Cargo"),
            ("status", "Status"),
            ("status_agendado", "Status agendado"),
            ("job", "Processo"),
        )
        alteracoes = []
        for chave, label in campos:
            de = anteriores.get(chave)
            para = novos.get(chave)
            if de != para and (chave in anteriores or chave in novos):
                alteracoes.append({"campo": label, "de": de or "—", "para": para or "—"})

        return {
            "id": self.id,
            "tipo": self.tipo,
            "operador_id": self.operador_id,
            "operador_login": self.operador_login or "",
            "operador_nome": self.operador_nome or "",
            "usuario_login": self.usuario_login or "",
            "usuario_nome": self.usuario_nome or "",
            "descricao": self.descricao or "",
            "dados_anteriores": self.dados_anteriores,
            "dados_novos": self.dados_novos,
            "alteracoes": alteracoes,
            "timestamp": self.timestamp.strftime("%d/%m/%Y %H:%M") if self.timestamp else None,
        }
