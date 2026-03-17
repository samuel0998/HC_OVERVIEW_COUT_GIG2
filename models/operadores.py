from flask_login import UserMixin

from models import db


class Operadores(db.Model, UserMixin):
    """Maps to the existing 'operadores' table in Railway.
    Only declares columns needed by HC View — existing columns are preserved.
    """
    __tablename__ = "operadores"
    __table_args__ = {"extend_existing": True}

    # Core identifier (primary key of the table)
    login = db.Column(db.String(50), primary_key=True)

    # Existing informational columns
    nome = db.Column(db.String(200), nullable=True)
    badge = db.Column(db.String(50), nullable=True)
    tag = db.Column(db.String(50), nullable=True)
    setor = db.Column(db.String(100), nullable=True)
    treinamento = db.Column(db.Boolean, nullable=True)

    # Existing permission columns (other apps)
    permission_labordash = db.Column(db.Boolean, default=False, nullable=True)
    permission_dockview = db.Column(db.Boolean, default=False, nullable=True)
    permission_level_labordash = db.Column(db.String(20), nullable=True)
    permission_level_dockview = db.Column(db.String(20), nullable=True)

    # NEW: HC View permission columns (added via migration in app.py)
    permission_hcview = db.Column(db.Boolean, default=False, nullable=True)
    permission_level_hcview = db.Column(db.String(20), nullable=True)  # admin | gestor | visualizador

    # ── Flask-Login interface ────────────────────────────────────

    def get_id(self):
        """Flask-Login uses this to store the user identifier in the session."""
        return self.login

    @property
    def is_admin(self):
        return self.permission_level_hcview == "admin"

    @property
    def is_gestor(self):
        return self.permission_level_hcview in ("admin", "gestor")

    @property
    def ativo(self):
        return bool(self.permission_hcview)

    def to_dict(self):
        return {
            "login": self.login,
            "nome": self.nome or self.login,
            "setor": self.setor or "",
            "permission_hcview": bool(self.permission_hcview),
            "permission_level_hcview": self.permission_level_hcview or "",
        }
