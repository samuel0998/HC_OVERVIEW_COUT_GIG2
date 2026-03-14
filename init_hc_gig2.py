from app import create_app
from models import db
from models.hc_gig2 import HCGig2

app = create_app()

with app.app_context():
    db.create_all()
    print("Tabela hc_gig2 criada/verificada com sucesso.")
