import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from routes.hc import _area_normalizada, _registro_cumpre_ticket, _ticket_resolver_url


def ticket(tipo, **campos):
    dados = {
        "premise_type": tipo,
        "sector_key": "out",
        "shift_name": "Night",
        "shift_key": "",
        "labor_type": "AA",
        "source_sector_key": "in",
        "source_shift_name": "Day",
        "source_shift_key": "",
        "source_labor_type": "AA",
    }
    dados.update(campos)
    return SimpleNamespace(**dados)


def registro(tipo, antes, depois):
    return SimpleNamespace(
        tipo=tipo,
        dados_anteriores=json.dumps(antes),
        dados_novos=json.dumps(depois),
    )


class TicketValidationTest(unittest.TestCase):
    def test_area_alias_in_matches_inbound(self):
        self.assertEqual(_area_normalizada("in"), _area_normalizada("INBOUND"))

    def test_toff_accepts_scheduled_termination_from_owner_sector(self):
        acao = registro(
            "edicao_status",
            {"cargo": "AA", "area": "INBOUND", "turno": "BLUE DAY", "status": "OPERACIONAL"},
            {"cargo": "AA", "area": "INBOUND", "turno": "BLUE DAY", "status": "OPERACIONAL", "status_agendado": "Desligado"},
        )
        self.assertTrue(_registro_cumpre_ticket(ticket("TOFF"), acao, "INBOUND", "BLUE DAY"))

    def test_toff_rejects_termination_outside_owner_sector(self):
        acao = registro(
            "edicao_status",
            {"cargo": "AA", "area": "ICQA", "turno": "BLUE DAY", "status": "OPERACIONAL"},
            {"cargo": "AA", "area": "ICQA", "turno": "BLUE DAY", "status": "Desligado"},
        )
        self.assertFalse(_registro_cumpre_ticket(ticket("TOFF"), acao, "INBOUND", "BLUE DAY"))

    def test_ls_accepts_matching_source_to_destination_move(self):
        acao = registro(
            "edicao",
            {"cargo": "PIT", "area": "INBOUND", "turno": "RED DAY", "status": "OPERACIONAL"},
            {"cargo": "PIT", "area": "OUTBOUND", "turno": "RED NIGHT", "status": "OPERACIONAL"},
        )
        premissa = ticket("LS", labor_type="PIT", source_labor_type="PIT")
        self.assertTrue(_registro_cumpre_ticket(premissa, acao, "INBOUND", "RED DAY"))

    def test_ls_rejects_wrong_destination(self):
        acao = registro(
            "edicao",
            {"cargo": "AA", "area": "INBOUND", "turno": "BLUE DAY"},
            {"cargo": "AA", "area": "ICQA", "turno": "BLUE NIGHT"},
        )
        self.assertFalse(_registro_cumpre_ticket(ticket("LS"), acao, "INBOUND", "BLUE DAY"))

    @patch("routes.hc._ticket_owner_contexto", return_value=("INBOUND", "BLUE DAY"))
    def test_resolver_url_uses_owner_filters_and_keeps_ticket_context(self, _contexto):
        premissa = ticket("TOFF", premise_id=42, is_transferencia=False)
        self.assertEqual(
            _ticket_resolver_url(premissa),
            "/atualizar?area=INBOUND&turno=BLUE+DAY&ticket_id=42",
        )


if __name__ == "__main__":
    unittest.main()
