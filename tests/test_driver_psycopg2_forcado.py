import importlib
import os
import unittest
from unittest.mock import patch


class DriverPsycopg2ForcadoTest(unittest.TestCase):
    """Toda URL de conexao Postgres tem que sair com 'postgresql+psycopg2://'
    explicito - nunca 'postgresql://' puro. Sem isso, dependendo de qual versao
    do SQLAlchemy o pip resolver num build, uma URL sem driver pode cair no
    dialeto psycopg (v3) em vez de psycopg2 (o unico instalado), derrubando o
    boot do gunicorn no Railway com ModuleNotFoundError: No module named
    'psycopg'. Ver config._forcar_driver_psycopg2."""

    def _reload_config(self, env):
        with patch.dict(os.environ, env, clear=False):
            import config
            return importlib.reload(config)

    def test_forca_driver_em_url_bare_postgresql(self):
        cfg = self._reload_config({"DATABASE_URL_GIG2": "postgresql://user:pw@host:5432/db"})
        self.assertEqual(cfg.Config.FC_DATABASES["GIG2"]["uri"], "postgresql+psycopg2://user:pw@host:5432/db")

    def test_forca_driver_em_url_estilo_heroku_postgres(self):
        cfg = self._reload_config({"DATABASE_URL_CNF2": "postgres://user:pw@host:5432/db"})
        self.assertEqual(cfg.Config.FC_DATABASES["CNF2"]["uri"], "postgresql+psycopg2://user:pw@host:5432/db")

    def test_preserva_query_string(self):
        cfg = self._reload_config({
            "DATABASE_URL_IXD_CNF2": "postgresql://user:pw@host:5432/db?connect_timeout=5",
        })
        self.assertEqual(
            cfg.Config.FC_DATABASES["IXD_CNF2"]["uri"],
            "postgresql+psycopg2://user:pw@host:5432/db?connect_timeout=5",
        )

    def test_idempotente_se_ja_vier_com_driver(self):
        cfg = self._reload_config({"DATABASE_URL_CWB1": "postgresql+psycopg2://user:pw@host:5432/db"})
        self.assertEqual(cfg.Config.FC_DATABASES["CWB1"]["uri"], "postgresql+psycopg2://user:pw@host:5432/db")

    def test_todos_os_fc_databases_tem_driver_explicito(self):
        cfg = self._reload_config({})
        for fc, dados in cfg.Config.FC_DATABASES.items():
            with self.subTest(fc=fc):
                self.assertTrue(
                    dados["uri"].startswith("postgresql+psycopg2://"),
                    f"{fc} sem driver explicito: {dados['uri'][:40]}",
                )


if __name__ == "__main__":
    unittest.main()
