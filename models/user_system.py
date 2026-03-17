from datetime import datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from models import db


class UserSystem(db.Model, UserMixin):
    __tablename__ = "user_system"

    id = db.Column(db.Integer, primary_key=True)
    login = db.Column(db.String(50), unique=True, nullable=False, index=True)
    nome = db.Column(db.String(150), nullable=False)
    senha_hash = db.Column(db.String(256), nullable=False)
    nivel_acesso = db.Column(db.String(20), nullable=False, default="gestor")  # admin, gestor, visualizador
    ativo = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_login = db.Column(db.DateTime, nullable=True)

    def set_senha(self, senha):
        self.senha_hash = generate_password_hash(senha)

    def check_senha(self, senha):
        return check_password_hash(self.senha_hash, senha)

    @property
    def is_admin(self):
        return self.nivel_acesso == "admin"

    def to_dict(self):
        return {
            "id": self.id,
            "login": self.login,
            "nome": self.nome,
            "nivel_acesso": self.nivel_acesso,
            "ativo": self.ativo,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "last_login": self.last_login.strftime("%Y-%m-%d %H:%M:%S") if self.last_login else None,
        }
