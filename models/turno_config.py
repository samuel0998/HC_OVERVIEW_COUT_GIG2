from datetime import datetime

from models import db


DEFAULT_TURNO_RESET = {
    "BLUE DAY": "20:00",
    "RED DAY": "20:00",
    "BLUE NIGHT": "08:00",
    "RED NIGHT": "08:00",
    "ADM": "17:00",
}


class HCTurnoConfig(db.Model):
    __tablename__ = "hc_turno_config"

    turno = db.Column(db.String(50), primary_key=True)
    hora_reset = db.Column(db.String(5), nullable=False)
    last_reset_key = db.Column(db.String(40), nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def to_dict(self):
        return {
            "turno": self.turno,
            "hora_reset": self.hora_reset,
            "last_reset_key": self.last_reset_key or "",
        }


def ensure_default_turno_config():
    existentes = {cfg.turno for cfg in HCTurnoConfig.query.all()}
    criados = 0
    for turno, hora in DEFAULT_TURNO_RESET.items():
        if turno not in existentes:
            db.session.add(HCTurnoConfig(turno=turno, hora_reset=hora))
            criados += 1
    return criados
