import unittest
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from models.hc_gig2 import HCGig2
from models.ticket import Ticket


FUSO = ZoneInfo("America/Sao_Paulo")


class TicketDeadlineAndLSReturnTest(unittest.TestCase):
    def test_ls_e_lt_vencem_no_mesmo_dia_no_horario_do_shift(self):
        data_solicitada = date(2026, 9, 7)
        for tipo in ("LS", "LT", "LM"):
            with self.subTest(tipo=tipo):
                ticket = Ticket(
                    premise_type=tipo,
                    work_date=data_solicitada,
                    escala="BLUE",
                    turno="Day",
                )
                self.assertEqual(ticket.prazo, data_solicitada)
                self.assertFalse(ticket.esta_vencido(datetime(2026, 9, 7, 7, 59, tzinfo=FUSO), "08:00"))
                self.assertTrue(ticket.esta_vencido(datetime(2026, 9, 7, 8, 1, tzinfo=FUSO), "08:00"))

    def test_outros_tipos_mantem_tres_dias_de_antecedencia(self):
        ticket = Ticket(premise_type="ON", work_date=date(2026, 9, 7))
        self.assertEqual(ticket.prazo, date(2026, 9, 4))

    def test_colaborador_retorna_para_origem_no_end_date_do_ls(self):
        colaborador = HCGig2(
            nome_completo="Teste LS",
            cargo="PIT",
            area="TRANSFER IN",
            turno="BLUE DAY",
            status="OPERACIONAL",
            ls_retorno_data=date(2026, 9, 13),
            ls_area_origem="INBOUND",
            ls_turno_origem="BLUE DAY",
            ls_ticket_id=275,
        )

        alterou = colaborador.aplicar_status_por_data(
            hoje=date(2026, 9, 13),
            agora=datetime(2026, 9, 13, 3),
        )

        self.assertTrue(alterou)
        self.assertEqual(colaborador.area, "INBOUND")
        self.assertEqual(colaborador.turno, "BLUE DAY")
        self.assertIsNone(colaborador.ls_retorno_data)
        self.assertIsNone(colaborador.ls_ticket_id)

    def test_status_ls_do_mesmo_dia_so_retorna_apos_24_horas(self):
        inicio = datetime(2026, 9, 13, 14, 30)
        colaborador = HCGig2(
            nome_completo="Teste LS manual",
            cargo="PIT",
            area="OUTBOUND",
            turno="BLUE DAY",
            status="LS",
            ls_retorno_data=date(2026, 9, 13),
            ls_retorno_em=inicio + timedelta(hours=24),
            ls_area_origem="INBOUND",
            ls_turno_origem="BLUE DAY",
        )

        self.assertFalse(colaborador.aplicar_status_por_data(
            hoje=date(2026, 9, 14), agora=inicio + timedelta(hours=23, minutes=59)
        ))
        self.assertEqual(colaborador.status, "LS")
        self.assertEqual(colaborador.area, "OUTBOUND")

        self.assertTrue(colaborador.aplicar_status_por_data(
            hoje=date(2026, 9, 14), agora=inicio + timedelta(hours=24)
        ))
        self.assertEqual(colaborador.status, "OPERACIONAL")
        self.assertEqual(colaborador.area, "INBOUND")


if __name__ == "__main__":
    unittest.main()
