import json
import unittest
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from routes.hc import (
    _area_normalizada,
    _janela_inicio_ticket,
    _registro_cumpre_ticket,
    _ticket_escala_lado,
    _ticket_owner_contexto,
    _ticket_resolver_url,
    _turno_corresponde,
)


def ticket(tipo, **campos):
    dados = {
        "premise_type": tipo,
        "is_transferencia": tipo in ("LS", "LT", "LM"),
        "sector_key": "out",
        "shift_name": "Night",
        "shift_key": "",
        "escala": "",
        "turno": "",
        "labor_type": "AA",
        "source_sector_key": "in",
        "source_shift_name": "Day",
        "source_shift_key": "",
        "escala_origem": "",
        "turno_origem": "",
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

    def test_area_alias_tfi_matches_transfer_in(self):
        self.assertEqual(_area_normalizada("tfi"), _area_normalizada("TRANSFER IN"))

    def test_area_alias_tfo_matches_transfer_out(self):
        self.assertEqual(_area_normalizada("tfo"), _area_normalizada("TRANSFER OUT"))

    def test_janela_ignora_created_at_futuro(self):
        # A ferramenta externa reescreve created_at a cada sync; a janela nao pode
        # comecar depois da acao que o usuario ja fez.
        work = date.today() + timedelta(days=1)
        t = SimpleNamespace(
            created_at=datetime.utcnow() + timedelta(hours=6),
            start_date=None,
            work_date=work,
        )
        inicio = _janela_inicio_ticket(t)
        self.assertLessEqual(inicio.date(), work - timedelta(days=30))

    def test_janela_usa_created_at_quando_e_o_mais_cedo(self):
        # work_date bem distante => (work_date - 30d) fica no futuro; created_at (ontem)
        # e' o limite mais cedo e deve ser usado como inicio da janela.
        t = SimpleNamespace(
            created_at=datetime.utcnow() - timedelta(days=1),
            start_date=None,
            work_date=date.today() + timedelta(days=45),
        )
        self.assertEqual(_janela_inicio_ticket(t), t.created_at)

    def test_owner_contexto_vem_do_ticket_nao_do_responsavel(self):
        # A origem do ticket e' BLUE DAY; o responsavel (que so' designa) e' outro.
        # _ticket_owner_contexto NAO pode consultar o HC do responsavel.
        premissa = ticket(
            "LT",
            source_sector_key="in", source_shift_name="BLUE DAY",
            source_responsible_login="bmarciod",
        )
        area, turno = _ticket_owner_contexto(premissa)
        self.assertEqual(_area_normalizada(area), _area_normalizada("INBOUND"))
        self.assertEqual(turno, "BLUE DAY")

    def test_escala_lado_prioriza_campo_do_ticket(self):
        self.assertEqual(_ticket_escala_lado("bmarciod", "BLUE DAY", ""), "BLUE DAY")

    def test_turno_corresponde_escala_sozinha(self):
        # turno_origem vem vazio -> ticket manda so' "BLUE"; deve casar com BLUE DAY/NIGHT
        self.assertTrue(_turno_corresponde("BLUE DAY", "BLUE"))
        self.assertTrue(_turno_corresponde("BLUE NIGHT", "BLUE"))
        self.assertFalse(_turno_corresponde("RED DAY", "BLUE"))
        self.assertTrue(_turno_corresponde("BLUE", "BLUE NIGHT"))

    def test_lt_valida_com_turno_origem_vazio(self):
        # Caso real (premise 275): origem IN / escala BLUE / turno_origem VAZIO,
        # destino OUT / BLUE / Day. Mover AA de INBOUND/BLUE DAY -> OUTBOUND/BLUE DAY.
        acao = registro(
            "edicao",
            {"cargo": "AA", "area": "INBOUND", "turno": "BLUE DAY", "status": "OPERACIONAL"},
            {"cargo": "AA", "area": "OUTBOUND", "turno": "BLUE DAY", "status": "OPERACIONAL"},
        )
        premissa = ticket(
            "LT", labor_type="AA", source_labor_type="AA",
            sector_key="OUTBOUND", shift_name="BLUE DAY",
            source_sector_key="INBOUND", source_shift_name="BLUE", source_shift_key="",
        )
        self.assertTrue(_registro_cumpre_ticket(premissa, acao, "INBOUND", "BLUE"))

    def test_lt_valida_move_blue_day_para_blue_day_mesma_escala(self):
        # Caso real: premissa IN/BLUE DAY -> TFI/BLUE DAY (so' muda o setor).
        acao = registro(
            "edicao",
            {"cargo": "PIT", "area": "INBOUND", "turno": "BLUE DAY", "status": "OPERACIONAL"},
            {"cargo": "PIT", "area": "TRANSFER IN", "turno": "BLUE DAY", "status": "OPERACIONAL"},
        )
        premissa = ticket(
            "LT", labor_type="PIT", source_labor_type="PIT",
            sector_key="tfi", shift_name="BLUE DAY",
            source_sector_key="in", source_shift_name="BLUE DAY",
        )
        self.assertTrue(_registro_cumpre_ticket(premissa, acao, "INBOUND", "BLUE DAY"))

    def test_lt_accepts_move_into_transfer_in_sector_code(self):
        acao = registro(
            "edicao",
            {"cargo": "PIT", "area": "INBOUND", "turno": "BLUE NIGHT", "status": "OPERACIONAL"},
            {"cargo": "PIT", "area": "TRANSFER IN", "turno": "BLUE DAY", "status": "OPERACIONAL"},
        )
        premissa = ticket(
            "LT", labor_type="PIT", source_labor_type="PIT",
            sector_key="tfi", shift_name="BLUE DAY",
            source_sector_key="in", source_shift_name="BLUE NIGHT",
        )
        self.assertTrue(_registro_cumpre_ticket(premissa, acao, "INBOUND", "BLUE NIGHT"))

    def test_toff_accepts_scheduled_termination_from_owner_sector(self):
        acao = registro(
            "edicao_status",
            {"cargo": "AA", "area": "INBOUND", "turno": "BLUE DAY", "status": "OPERACIONAL"},
            {"cargo": "AA", "area": "INBOUND", "turno": "BLUE DAY", "status": "OPERACIONAL", "status_agendado": "Desligado"},
        )
        premissa = ticket("TOFF", sector_key="INBOUND", shift_name="BLUE DAY", escala="BLUE", turno="Day")
        self.assertTrue(_registro_cumpre_ticket(premissa, acao, "INBOUND", "BLUE DAY"))

    def test_toff_rejects_termination_outside_owner_sector(self):
        acao = registro(
            "edicao_status",
            {"cargo": "AA", "area": "ICQA", "turno": "BLUE DAY", "status": "OPERACIONAL"},
            {"cargo": "AA", "area": "ICQA", "turno": "BLUE DAY", "status": "Desligado"},
        )
        premissa = ticket("TOFF", sector_key="INBOUND", shift_name="BLUE DAY", escala="BLUE", turno="Day")
        self.assertFalse(_registro_cumpre_ticket(premissa, acao, "INBOUND", "BLUE DAY"))

    def test_lt_rejeita_escala_errada(self):
        # ticket pede origem BLUE; colaborador movido e' RED -> nao valida
        acao = registro(
            "edicao",
            {"cargo": "AA", "area": "INBOUND", "turno": "RED DAY", "status": "OPERACIONAL"},
            {"cargo": "AA", "area": "OUTBOUND", "turno": "RED DAY", "status": "OPERACIONAL"},
        )
        premissa = ticket(
            "LT", labor_type="AA", source_labor_type="AA",
            source_sector_key="INBOUND", escala_origem="BLUE", turno_origem="Day",
            sector_key="OUTBOUND", escala="BLUE", turno="Day", shift_name="BLUE DAY", source_shift_name="BLUE DAY",
        )
        self.assertFalse(_registro_cumpre_ticket(premissa, acao, "INBOUND", "BLUE DAY"))

    def test_lt_rejeita_periodo_errado(self):
        # ticket pede destino Day; colaborador foi para Night -> nao valida
        acao = registro(
            "edicao",
            {"cargo": "AA", "area": "INBOUND", "turno": "BLUE DAY", "status": "OPERACIONAL"},
            {"cargo": "AA", "area": "OUTBOUND", "turno": "BLUE NIGHT", "status": "OPERACIONAL"},
        )
        premissa = ticket(
            "LT", labor_type="AA", source_labor_type="AA",
            source_sector_key="INBOUND", escala_origem="BLUE", turno_origem="Day",
            sector_key="OUTBOUND", escala="BLUE", turno="Day", shift_name="BLUE DAY", source_shift_name="BLUE DAY",
        )
        self.assertFalse(_registro_cumpre_ticket(premissa, acao, "INBOUND", "BLUE DAY"))

    def test_on_valida_novo_pit_em_treinamento_turno_adm(self):
        # New Hire: cadastro entra como Treinamento e PIT recebe turno 'ADM'.
        # A escala/periodo do ticket nao pode bloquear - so' cargo + setor.
        acao = registro(
            "adicao",
            {},
            {"cargo": "PIT", "area": "INBOUND", "turno": "ADM", "status": "Treinamento"},
        )
        premissa = ticket(
            "ON", labor_type="PIT",
            sector_key="INBOUND", escala="BLUE", turno="Night", shift_name="BLUE NIGHT",
        )
        self.assertTrue(_registro_cumpre_ticket(premissa, acao, "INBOUND", "BLUE NIGHT"))

    def test_on_rejeita_setor_errado(self):
        acao = registro(
            "adicao",
            {},
            {"cargo": "PIT", "area": "OUTBOUND", "turno": "ADM", "status": "Treinamento"},
        )
        premissa = ticket("ON", labor_type="PIT", sector_key="INBOUND", shift_name="BLUE NIGHT")
        self.assertFalse(_registro_cumpre_ticket(premissa, acao, "INBOUND", "BLUE NIGHT"))

    def test_lt_rejeita_cargo_errado(self):
        # ticket pede PIT; moveram um Analista -> nao valida
        acao = registro(
            "edicao",
            {"cargo": "Analista", "area": "INBOUND", "turno": "BLUE DAY", "status": "OPERACIONAL"},
            {"cargo": "Analista", "area": "OUTBOUND", "turno": "BLUE DAY", "status": "OPERACIONAL"},
        )
        premissa = ticket(
            "LT", labor_type="PIT", source_labor_type="PIT",
            source_sector_key="INBOUND", escala_origem="BLUE", turno_origem="Day",
            sector_key="OUTBOUND", escala="BLUE", turno="Day", shift_name="BLUE DAY", source_shift_name="BLUE DAY",
        )
        self.assertFalse(_registro_cumpre_ticket(premissa, acao, "INBOUND", "BLUE DAY"))

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
        # ticket manda labor_type "AA"; o link deve filtrar por "Associado" (cargo consolidado)
        premissa = ticket("TOFF", premise_id=42, is_transferencia=False)
        self.assertEqual(
            _ticket_resolver_url(premissa),
            "/atualizar?area=INBOUND&turno=BLUE+DAY&cargo=Associado&ticket_id=42",
        )

    @patch("routes.hc._ticket_owner_contexto", return_value=("INBOUND", "RED DAY"))
    def test_resolver_url_transfer_uses_source_cargo(self, _contexto):
        premissa = ticket(
            "LS", premise_id=7, is_transferencia=True,
            source_labor_type="PIT", labor_type="AA",
        )
        self.assertEqual(
            _ticket_resolver_url(premissa),
            "/atualizar?area=INBOUND&turno=RED+DAY&cargo=PIT&ticket_id=7",
        )


if __name__ == "__main__":
    unittest.main()
