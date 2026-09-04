from flask_login import UserMixin

from models import db

# Permission level hierarchy (lowest to highest)
#   LC1              → Dashboard/LC only
#   LC3              → + Novo HC, LIST, Pendências
#   LC5              → tudo, exceto Histórico e Excluir colaborador
#   LC-RH-ANALYTICS  → como LC5, mas SEM cadastrar (Novo HC) e SEM excluir
#   EXPERT           → acesso total (Histórico, Excluir, Usuários)
#   LC-HARD-EXPERT   → EXPERT + gestão de tickets de premissa (arquivar/cancelar).
#                      Só o time de Planning tem; só o login 'sxmoraes' concede.
NIVELS_HC = ["LC1", "LC3", "LC5", "LC-RH-ANALYTICS", "EXPERT", "LC-HARD-EXPERT"]
NIVEIS_EXPERT = ("EXPERT", "LC-HARD-EXPERT")
LOGIN_CONCEDE_HARD_EXPERT = "sxmoraes"


def _nivel_gte(nivel_usuario, nivel_minimo):
    """Returns True if the user's level is >= the required minimum."""
    try:
        return NIVELS_HC.index(nivel_usuario) >= NIVELS_HC.index(nivel_minimo)
    except ValueError:
        return False


class Operadores(db.Model, UserMixin):
    """Maps to the existing 'operadores' table in Railway.
    Only declares columns needed by HC View — existing columns are preserved.
    """
    __bind_key__ = "GIG2"
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

    # HC View permission columns (added via migration in app.py)
    # permission_level_hcview values: ver NIVELS_HC acima
    permission_hcview = db.Column(db.Boolean, default=False, nullable=True)
    permission_level_hcview = db.Column(db.String(20), nullable=True)

    # ── Flask-Login interface ────────────────────────────────────

    def get_id(self):
        """Flask-Login uses this to store the user identifier in the session."""
        return self.login

    # ── Permission gates ─────────────────────────────────────────
    # LC1   → Dashboard only
    # LC3   → Dashboard + Novo HC + Atualizar + Pendências
    # LC5   → Everything except Histórico and Excluir colaborador
    # EXPERT → Full access (includes Histórico, Excluir, Usuários)

    @property
    def nivel(self):
        return self.permission_level_hcview or ""

    @property
    def can_dashboard(self):
        """LC1+ can access Dashboard."""
        return bool(self.permission_hcview) and self.nivel in NIVELS_HC

    @property
    def can_edit(self):
        """LC3+ can access Atualizar (LIST) e Pendências."""
        return bool(self.permission_hcview) and _nivel_gte(self.nivel, "LC3")

    @property
    def can_add_colaborador(self):
        """Cadastrar novo colaborador (Novo HC). Como can_edit, mas LC-RH-ANALYTICS
        NÃO pode cadastrar."""
        return self.can_edit and self.nivel != "LC-RH-ANALYTICS"

    @property
    def can_delete(self):
        """EXPERT/HARD EXPERT only can delete collaborators."""
        return bool(self.permission_hcview) and self.nivel in NIVEIS_EXPERT

    @property
    def can_historico(self):
        """EXPERT/HARD EXPERT only can access Histórico."""
        return bool(self.permission_hcview) and self.nivel in NIVEIS_EXPERT

    @property
    def is_admin(self):
        """EXPERT/HARD EXPERT = admin (manages permissions, sees Usuários nav)."""
        return bool(self.permission_hcview) and self.nivel in NIVEIS_EXPERT

    @property
    def is_hard_expert(self):
        """LC-HARD-EXPERT (Planning): pode arquivar e cancelar tickets de premissa."""
        return bool(self.permission_hcview) and self.nivel == "LC-HARD-EXPERT"

    @property
    def pode_conceder_hard_expert(self):
        """Só o login definido em LOGIN_CONCEDE_HARD_EXPERT concede LC-HARD-EXPERT."""
        return (self.login or "").strip().lower() == LOGIN_CONCEDE_HARD_EXPERT

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
