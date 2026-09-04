import unittest

from routes.hc import _horas_float, _lc_por_horas


class LCHoursTest(unittest.TestCase):
    def test_faixas_de_lc(self):
        casos = {
            0: "LC1",
            40: "LC1",
            40.01: "LC2",
            80: "LC2",
            80.01: "LC3",
            120: "LC3",
            120.01: "LC4",
            160: "LC4",
            160.01: "LC5",
            400: "LC5",
            400.01: "LC6(VET)",
        }
        for horas, esperado in casos.items():
            with self.subTest(horas=horas):
                self.assertEqual(_lc_por_horas(horas), esperado)

    def test_horas_em_formato_brasileiro(self):
        self.assertEqual(_horas_float("1.234,56"), 1234.56)
        self.assertEqual(_horas_float("40,01"), 40.01)
        self.assertIsNone(_horas_float(""))


if __name__ == "__main__":
    unittest.main()
