from datetime import datetime

from models import db


class LCAtual(db.Model):
    __tablename__ = "lc_atual"

    id = db.Column(db.Integer, primary_key=True)
    login = db.Column(db.String(50), nullable=False, index=True)
    process_name = db.Column(db.String(150), nullable=False, index=True)
    lc_level = db.Column(db.String(50), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "login": self.login or "",
            "process_name": self.process_name or "",
            "lc_level": self.lc_level or "",
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }
