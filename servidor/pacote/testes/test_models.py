"""VersaoPacote (004b R2, R20; A2): unicidade, uma só vigente, RLS e privilégio mínimo do papel `app`."""

import threading

import pytest
from django.db import IntegrityError, ProgrammingError, connection, connections, transaction

from pacote.models import VersaoPacote
from permissao.pode import com_permissao

MANIFESTO = {'formato_versao': 1}  # o modelo não valida o JSON; quem valida é `manifesto.py`


def _versao(cenario, numero, vigente=False, fazenda=None):
    fazenda = fazenda or cenario.f1
    return VersaoPacote.objects.create(
        empresa_id=fazenda.empresa_id, fazenda=fazenda, numero=numero, manifesto=MANIFESTO, vigente=vigente,
    )


def test_papel_app_e_escapado_como_identificador(settings):
    # `quote_name` do Django devolveria `"a"b"`; o identificador escapado dobra as aspas.
    from importlib import import_module

    settings.DATABASES = {**settings.DATABASES, 'app': {**settings.DATABASES['app'], 'USER': 'a"b; DROP TABLE x; --'}}
    migracao = import_module('pacote.migrations.0001_initial')
    editor = type('Editor', (), {'connection': connection})()
    assert migracao.papel_app(editor) == '"a""b; DROP TABLE x; --"'


def test_numero_repetido_na_mesma_fazenda_e_recusado(cenario):
    _versao(cenario, 1)
    with pytest.raises(IntegrityError), transaction.atomic():
        _versao(cenario, 1)
    _versao(cenario, 1, fazenda=cenario.f2)  # outra fazenda pode ter o número 1


def test_numero_zero_e_recusado(cenario):
    with pytest.raises(IntegrityError), transaction.atomic():
        _versao(cenario, 0)


def test_duas_vigentes_na_mesma_fazenda_sao_recusadas(cenario):
    _versao(cenario, 1, vigente=True)
    with pytest.raises(IntegrityError), transaction.atomic():
        _versao(cenario, 2, vigente=True)
    _versao(cenario, 2, vigente=False)
    _versao(cenario, 1, vigente=True, fazenda=cenario.f2)  # a regra é por fazenda


def test_empresa_de_outra_fazenda_e_recusada_pela_chave_composta(cenario):
    with pytest.raises(IntegrityError), transaction.atomic():
        VersaoPacote.objects.create(empresa_id=cenario.y.pk, fazenda=cenario.f1, numero=1, manifesto=MANIFESTO)


pytestmark_app = pytest.mark.django_db(transaction=True, databases=['default', 'app'])


@pytestmark_app
def test_o_papel_app_so_ve_a_versao_da_propria_empresa(catalogo_da_corrida, cenario, fabrica_pessoa, conceder_direto):
    _versao(cenario, 1, vigente=True)
    _versao(cenario, 1, vigente=True, fazenda=cenario.fy)
    de_y = fabrica_pessoa('Administrador de Y')
    conceder_direto(de_y, cenario.cargos_y['administrador'], cenario.y)
    de_x = fabrica_pessoa('Administrador de X')
    conceder_direto(de_x, cenario.cargos_x['administrador'], cenario.x)
    sem_vinculo = fabrica_pessoa('Sem vinculo')

    def lidas(pessoa):
        with com_permissao(pessoa, usando='app'), connections['app'].cursor() as cursor:
            cursor.execute('SELECT fazenda_id FROM versao_pacote ORDER BY fazenda_id')
            return [linha[0] for linha in cursor.fetchall()]

    assert lidas(de_x) == [cenario.f1.pk]
    assert lidas(de_y) == [cenario.fy.pk]
    assert lidas(sem_vinculo) == []  # sem escopo, nenhuma linha (acesso negado)


@pytestmark_app
def test_o_papel_app_so_atualiza_vigente_e_nunca_apaga(catalogo_da_corrida, cenario, plataforma):
    versao = _versao(cenario, 1, vigente=True)
    with com_permissao(plataforma, usando='app'), connections['app'].cursor() as cursor:
        cursor.execute('UPDATE versao_pacote SET vigente = false WHERE id = %s', [versao.pk])
        assert cursor.rowcount == 1
    for sql in (
        'UPDATE versao_pacote SET numero = 9 WHERE id = %s',
        "UPDATE versao_pacote SET manifesto = '{}' WHERE id = %s",
        'DELETE FROM versao_pacote WHERE id = %s',
    ):
        with pytest.raises(ProgrammingError), com_permissao(plataforma, usando='app'), connections['app'].cursor() as cursor:
            cursor.execute(sql, [versao.pk])


@pytestmark_app
def test_duas_conexoes_simultaneas_nunca_deixam_duas_vigentes(catalogo_da_corrida, cenario):
    # O índice parcial é a defesa final: duas transações que tentam gravar a vigente 2 ao mesmo tempo, só uma vence.
    _versao(cenario, 1, vigente=True)
    resultados = []

    def tentar(numero):
        try:
            with transaction.atomic():
                VersaoPacote.objects.filter(fazenda=cenario.f1, vigente=True).update(vigente=False)
                _versao(cenario, numero, vigente=True)
            resultados.append('ok')
        except IntegrityError:
            resultados.append('recusada')
        finally:
            connection.close()

    fios = [threading.Thread(target=tentar, args=(n,)) for n in (2, 3)]
    for fio in fios:
        fio.start()
    for fio in fios:
        fio.join()
    assert VersaoPacote.objects.filter(fazenda=cenario.f1, vigente=True).count() == 1
    assert 'ok' in resultados
