import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.auth.models import AnonymousUser
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase

from programar.services.termo_ciencia import montar_termo_ciencia
from programar.views_legacy import relatorios_parcial


def servidor(pk=1, nome="Marcelo", matricula="123"):
    return SimpleNamespace(pk=pk, nome=nome, matricula=matricula)


def item(pk, dia, atividade="PVBR", meta_id=1, cancelada=False):
    return SimpleNamespace(
        pk=pk, programacao=SimpleNamespace(data=dia),
        meta=SimpleNamespace(display_titulo=atividade), meta_id=meta_id,
        cancelada=cancelada,
    )


def vinculo(item_id, pessoa):
    return SimpleNamespace(item_id=item_id, servidor=pessoa)


class TermoCienciaDadosTest(SimpleTestCase):
    def montar(self, inicio, fim, itens=(), vinculos=(), programacoes=(), status=None, unidade_id=7):
        with (
            patch("programar.services.termo_ciencia.Programacao.objects.filter") as progs,
            patch("programar.services.termo_ciencia.ProgramacaoItem.objects.filter") as atividades,
            patch("programar.services.termo_ciencia.ProgramacaoItemServidor.objects.filter") as links,
        ):
            progs.return_value = programacoes
            atividades.return_value.select_related.return_value = itens
            links.return_value.select_related.return_value = vinculos
            result = montar_termo_ciencia(
                unidade_id, inicio, fim,
                status_para_data=status or (lambda *_: ([], [], [], [])),
                expediente_desativado=lambda obs: obs == "desativado",
            )
            self.filtros = (
                progs.call_args, atividades.call_args, links.call_args,
            )
            return result

    def test_agrupa_atividades_e_deduplica_dias_inclusivos_em_virada_de_mes(self):
        inicio, fim = date(2026, 11, 30), date(2026, 12, 1)
        marcelo, ana = servidor(), servidor(2, "Ana")
        result = self.montar(
            inicio, fim,
            itens=[item(10, inicio), item(11, fim), item(12, fim)],
            vinculos=[
                vinculo(10, marcelo), vinculo(11, marcelo),
                vinculo(12, marcelo), vinculo(12, ana),
            ],
        )
        self.assertEqual([s["nome"] for s in result], ["Ana", "Marcelo"])
        self.assertEqual(result[1]["atividades"], [{
            "nome": "PVBR", "dias": ["seg. 30/11/2026", "ter. 01/12/2026"],
        }])
        self.assertEqual(self.filtros[0].kwargs, {
            "unidade_id": 7, "data__gte": inicio, "data__lte": fim,
        })
        self.assertEqual(self.filtros[1].kwargs["programacao__unidade_id"], 7)
        self.assertFalse(self.filtros[1].kwargs["cancelada"])
        self.assertNotIn("servidor__unidade_id", self.filtros[2].kwargs)

    def test_expediente_automatico_e_manual_junto_com_atividade_de_campo(self):
        inicio, fim = date(2026, 11, 2), date(2026, 11, 5)
        marcelo = servidor()
        result = self.montar(
            inicio, fim,
            itens=[
                item(10, date(2026, 11, 3)),
                item(11, date(2026, 11, 4)),
                item(12, date(2026, 11, 3), "Expediente administrativo", 999909),
            ],
            vinculos=[vinculo(10, marcelo), vinculo(11, marcelo), vinculo(12, marcelo)],
            status=lambda *_: ([{"id": 1, "nome": "Marcelo"}], [], [], []),
        )
        atividades = {a["nome"]: a["dias"] for a in result[0]["atividades"]}
        self.assertEqual(atividades["Expediente administrativo"], [
            "seg. 02/11/2026", "ter. 03/11/2026", "qui. 05/11/2026",
        ])
        self.assertEqual(atividades["PVBR"], ["ter. 03/11/2026", "qua. 04/11/2026"])
        self.assertEqual(result[0]["matricula"], "123")

    def test_nao_cria_expediente_em_feriado_dia_desativado_ou_fim_de_semana_vazio(self):
        pessoa = servidor()
        for dia, feriados, observacao in (
            (date(2026, 11, 2), [{"descricao": "Feriado"}], ""),
            (date(2026, 11, 3), [], "desativado"),
            (date(2026, 11, 8), [], ""),
        ):
            with self.subTest(dia=dia):
                result = self.montar(
                    dia, dia,
                    programacoes=[SimpleNamespace(data=dia, observacao=observacao)],
                    status=lambda *_: ([{"id": 1, "nome": pessoa.nome}], [], feriados, []),
                )
                self.assertEqual(result, [])

    def test_atividade_em_feriado_permanece_sem_expediente(self):
        dia = date(2026, 11, 2)
        result = self.montar(
            dia, dia,
            itens=[item(10, dia), item(11, dia, "Expediente administrativo", 999909)],
            vinculos=[vinculo(10, servidor()), vinculo(11, servidor())],
            status=lambda *_: ([{"id": 1, "nome": "Marcelo"}], [], [{"descricao": "Feriado"}], []),
        )
        self.assertEqual([a["nome"] for a in result[0]["atividades"]], ["PVBR"])

    def test_nao_inclui_canceladas_nem_expediente_para_impedidos(self):
        dia = date(2026, 11, 3)
        result = self.montar(
            dia, dia,
            itens=[item(10, dia, cancelada=True)],
            vinculos=[vinculo(10, servidor())],
            status=lambda *_: ([{"id": 2, "nome": "Ana"}], [{"id": 2}], [], []),
        )
        self.assertEqual(result, [])

    def test_pessoas_com_mesmo_nome_tem_assinaturas_separadas(self):
        dia = date(2026, 11, 3)
        result = self.montar(
            dia, dia, itens=[item(10, dia)],
            vinculos=[vinculo(10, servidor(1)), vinculo(10, servidor(2))],
        )
        self.assertEqual(len(result), 2)
        self.assertEqual({s["id"] for s in result}, {1, 2})

    def test_periodo_invertido_ou_sem_unidade_nao_consulta_banco(self):
        for inicio, fim, unidade in (
            (date(2026, 11, 5), date(2026, 11, 2), 7),
            (date(2026, 11, 2), date(2026, 11, 5), None),
        ):
            self.assertEqual(self.montar(inicio, fim, unidade_id=unidade), [])
            self.assertTrue(all(call is None for call in self.filtros))

    def test_template_tem_assinatura_por_servidor_e_escapa_conteudo(self):
        rendered = render_to_string("programar/partials/_termo_ciencia.html", {
            "inicio": date(2026, 11, 2), "fim": date(2026, 11, 5),
            "unidade": "<script>unidade</script>",
            "servidores": [
                {"id": 1, "nome": "<img src=x>", "atividades": [
                    {"nome": "<b>PVBR</b>", "dias": ["ter. 03/11/2026"]},
                ]},
                {"id": 2, "nome": "Ana", "atividades": []},
            ],
        })
        self.assertTrue(rendered.lstrip().startswith('<section id="relatorio-termo-ciencia"'))
        self.assertEqual(rendered.count("Assinatura do servidor"), 2)
        self.assertIn("02/11/2026 a 05/11/2026", rendered)
        self.assertIn("&lt;img src=x&gt;", rendered)
        self.assertIn("&lt;b&gt;PVBR&lt;/b&gt;", rendered)
        self.assertNotIn("<script>", rendered)


class TermoCienciaEndpointTest(SimpleTestCase):
    def request(self, params):
        request = RequestFactory().get("/programar/relatorios/", params)
        request.user = SimpleNamespace(is_authenticated=True)
        request.session = {}
        return request

    @patch("programar.views_legacy.get_unidade_atual", return_value="Unidade de teste")
    @patch("programar.views_legacy.get_unidade_atual_id", return_value=7)
    @patch("programar.views_legacy.montar_termo_ciencia", return_value=[])
    def test_opcao_gera_termo_do_periodo_sem_relatorio_de_justificativas(self, montar, *_):
        response = relatorios_parcial(self.request({
            "start": "2026-11-02", "end": "2026-11-05", "only_ciencia": "1",
        }))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertTrue(payload["ok"])
        self.assertIn('id="relatorio-termo-ciencia"', payload["html"])
        self.assertIn("Nenhum servidor", payload["html"])
        self.assertEqual(montar.call_args.args, (7, date(2026, 11, 2), date(2026, 11, 5)))

    @patch("programar.views_legacy.get_unidade_atual_id", return_value=7)
    @patch("programar.views_legacy.montar_termo_ciencia")
    def test_rejeita_periodo_invalido_sem_consultar_dados(self, montar, *_):
        for start, end in (("invalido", "2026-11-05"), ("2026-11-05", "2026-11-02")):
            response = relatorios_parcial(self.request({
                "start": start, "end": end, "only_ciencia": "1",
            }))
            self.assertEqual(response.status_code, 400)
        montar.assert_not_called()

    @patch("programar.views_legacy.get_unidade_atual_id", return_value=None)
    @patch("programar.views_legacy.montar_termo_ciencia")
    def test_rejeita_ausencia_de_unidade(self, montar, *_):
        response = relatorios_parcial(self.request({
            "start": "2026-11-02", "end": "2026-11-05", "only_ciencia": "1",
        }))
        self.assertEqual(response.status_code, 400)
        montar.assert_not_called()

    def test_exige_login(self):
        request = self.request({"only_ciencia": "1"})
        request.user = AnonymousUser()
        with self.settings(ALLOWED_HOSTS=["testserver"]):
            self.assertEqual(relatorios_parcial(request).status_code, 302)


class RelatoriosConsistenciaTest(SimpleTestCase):
    def renderizar(self, itens):
        from programar.views_legacy import _render_programacao_semana_html
        request = RequestFactory().get('/programar/relatorios/', {'only_just': '1'})
        with (
            patch('programar.views_legacy.get_unidade_atual_id', return_value=None),
            patch('programar.views_legacy._fetch_programacao_dia', return_value=itens),
            patch('programar.views_legacy._fetch_expediente_admin', return_value=([], [])),
        ):
            return _render_programacao_semana_html(request, '2026-11-03', '2026-11-03')

    def test_justificativas_separam_servidores_homonimos(self):
        rendered = self.renderizar([
            {'meta': 'Fiscalizacao', 'servidores': ['Ana', 'Ana'],
             'servidor_ids': ['1', '2'], 'veiculo': ''},
        ])
        self.assertEqual(rendered.count('Servidor: Ana'), 2)

    def test_metas_distintas_com_mesmo_titulo_preservam_atividade_sem_servidor(self):
        from programar.views_legacy import _render_programacao_semana_html
        request = RequestFactory().get('/programar/relatorios/', {'hide_just': '1'})
        with (
            patch('programar.views_legacy.get_unidade_atual_id', return_value=None),
            patch('programar.views_legacy._fetch_programacao_dia', return_value=[
                {'meta_id': 1, 'meta': 'Fiscalizacao', 'servidores': ['Ana'],
                 'servidor_ids': ['1'], 'veiculo': '', 'observacao': 'Primeira meta'},
                {'meta_id': 2, 'meta': 'Fiscalizacao', 'servidores': [],
                 'servidor_ids': [], 'veiculo': '', 'observacao': 'Segunda meta'},
            ]),
            patch('programar.views_legacy._fetch_expediente_admin', return_value=([], [])),
        ):
            rendered = _render_programacao_semana_html(request, '2026-11-03', '2026-11-03')
        self.assertIn('Primeira meta', rendered)
        self.assertIn('Segunda meta', rendered)
