from flask import Flask

from config import Config
from models import db
from routes.hc import hc_bp


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)

    with app.app_context():
        from models.hc_gig2 import HCGig2  # noqa: F401
        db.create_all()
        # Add new columns to existing tables without dropping data
        try:
            db.session.execute(db.text(
                "ALTER TABLE hc_gig2 ADD COLUMN IF NOT EXISTS status_liberacao VARCHAR(100)"
            ))
            db.session.execute(db.text(
                "ALTER TABLE hc_gig2 ALTER COLUMN login DROP NOT NULL"
            ))
            db.session.execute(db.text(
                "ALTER TABLE hc_gig2 ALTER COLUMN area DROP NOT NULL"
            ))
            db.session.execute(db.text(
                "ALTER TABLE hc_gig2 ALTER COLUMN turno DROP NOT NULL"
            ))
            db.session.execute(db.text(
                "ALTER TABLE hc_gig2 ADD COLUMN IF NOT EXISTS data_inicio_licenca DATE"
            ))
            db.session.execute(db.text(
                "ALTER TABLE hc_gig2 ADD COLUMN IF NOT EXISTS data_fim_licenca DATE"
            ))
            db.session.execute(db.text(
                "ALTER TABLE hc_gig2 ADD COLUMN IF NOT EXISTS data_desligamento DATE"
            ))
            db.session.execute(db.text(
                "ALTER TABLE hc_gig2 ALTER COLUMN causa_afastamento TYPE VARCHAR(500)"
            ))
            db.session.commit()

            # Verificação das colunas após migração
            result = db.session.execute(db.text(
                "SELECT column_name, data_type, is_nullable "
                "FROM information_schema.columns "
                "WHERE table_name = 'hc_gig2' "
                "ORDER BY ordinal_position"
            ))
            colunas = result.fetchall()
            print("=== [MIGRATION] Estrutura atual da tabela hc_gig2 ===")
            for col in colunas:
                print(f"  {col[0]:30s} | {col[1]:20s} | nullable={col[2]}")
            print("=== [MIGRATION] Concluída com sucesso ===")

        except Exception as e:
            db.session.rollback()
            print(f"[MIGRATION] ERRO ao aplicar migração: {e}")

    app.register_blueprint(hc_bp)
    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
