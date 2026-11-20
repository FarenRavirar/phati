"""Metadados e atributos da prévia (008 T2.3; R8, R9, R10, R21): feliz e infeliz, com envio sintético."""

import pytest

from catalogo.ingestao import FeicaoPrevia, Previa, RecusaIngestao, ingerir_envio
from catalogo.metadados import OBRIGATORIOS, OPCIONAIS, atributos_da_previa, montar_previa, validar_metadados
from catalogo.testes.test_ingestao import arquivo, geojson

MINIMO = {'nome': 'Solo sintético', 'tema': 'Solo', 'origem': 'Levantamento sintético'}


def feicao_geojson(x, props):
    return {'type': 'Feature', 'properties': props, 'geometry': {'type': 'Point', 'coordinates': [x, -10.7]}}


def previa_sintetica(campos, valores_por_feicao):
    feicoes = tuple(FeicaoPrevia(None, dict(v)) for v in valores_por_feicao)
    return Previa(
        formato='geojson', tipo='ponto', sistema='EPSG:4326', origem_sistema='x', transformacao='equivalencia',
        avisos=(), extensao=(0, 0, 0, 0), feicoes=feicoes, campos=tuple(campos),
    )


# Caminho feliz

def test_so_obrigatorios_publica_e_opcionais_viram_sem_dados(tmp_path):
    previa = ingerir_envio(arquivo(tmp_path, geojson([feicao_geojson(-48.3, {'codigo': 'A1'})])))
    completa = montar_previa(previa, MINIMO)
    assert completa.metadados.obrigatorios == MINIMO
    assert set(completa.metadados.opcionais) == set(OPCIONAIS)
    assert all(valor is None for valor in completa.metadados.opcionais.values())


def test_colunas_do_arquivo_viram_atributos_e_ausente_fica_ausente(tmp_path):
    envio = geojson([
        feicao_geojson(-48.3, {'codigo': 'A1', 'area': 2.5, 'obs': None}),
        feicao_geojson(-48.2, {'codigo': 'A2', 'area': 0, 'obs': None}),
    ])
    completa = montar_previa(ingerir_envio(arquivo(tmp_path, envio)), MINIMO)
    por_nome = {atributo.nome: atributo for atributo in completa.atributos}
    assert set(por_nome) == {'codigo', 'area', 'obs'}
    assert por_nome['area'].valores == (2.5, 0)  # zero continua zero
    assert por_nome['area'].tipo == 'numero'
    assert por_nome['obs'].valores == (None, None)  # ausente continua ausente
    assert por_nome['obs'].tipo == 'vazio'
    assert por_nome['codigo'].tipo == 'texto'


def test_nome_de_coluna_com_marcacao_e_guardado_como_veio(tmp_path):
    # R21: texto do arquivo é hostil e é escapado na tela (T4); aqui só não pode ser alterado nem interpretado.
    completa = montar_previa(ingerir_envio(arquivo(tmp_path, geojson([feicao_geojson(-48.3, {'<b>x</b>': 'y'})]))), MINIMO)
    assert [atributo.nome for atributo in completa.atributos] == ['<b>x</b>']


def test_lista_ou_objeto_e_tipo_estrutura_e_mistura_com_texto_e_misto():
    assert atributos_da_previa(previa_sintetica(['v'], [{'v': [1]}, {'v': {'a': 1}}]))[0].tipo == 'estrutura'
    assert atributos_da_previa(previa_sintetica(['v'], [{'v': [1]}, {'v': 'x'}]))[0].tipo == 'misto'


def test_tipo_misto_e_marcado_sem_converter_valores():
    previa = previa_sintetica(['codigo'], [{'codigo': 1}, {'codigo': 'abc'}])
    atributo = atributos_da_previa(previa)[0]
    assert atributo.tipo == 'misto'
    assert atributo.valores == (1, 'abc')


# Caminho infeliz: metadados

@pytest.mark.parametrize('campo', OBRIGATORIOS)
def test_obrigatorio_ausente_e_recusado(campo):
    bruto = dict(MINIMO)
    del bruto[campo]
    with pytest.raises(RecusaIngestao) as excinfo:
        validar_metadados(bruto)
    assert f'{campo} é obrigatório' in excinfo.value.erros


@pytest.mark.parametrize('valor', ['', '   ', None])
def test_obrigatorio_vazio_ou_so_espacos_e_recusado(valor):
    bruto = dict(MINIMO, origem=valor)
    with pytest.raises(RecusaIngestao) as excinfo:
        validar_metadados(bruto)
    assert 'origem é obrigatório' in excinfo.value.erros


def test_zero_no_opcional_nao_vira_sem_dados_nem_texto():
    # Zero é valor informado, não ausente: como não é texto, é recusado. Não vira "Sem dados" nem "0".
    with pytest.raises(RecusaIngestao) as excinfo:
        validar_metadados(dict(MINIMO, escala_resolucao=0))
    assert 'escala_resolucao deve ser texto' in excinfo.value.erros[0]


def test_campo_desconhecido_e_recusado():
    with pytest.raises(RecusaIngestao) as excinfo:
        validar_metadados(dict(MINIMO, campo_inventado='x'))
    assert 'metadado desconhecido' in excinfo.value.erros[0]


def test_texto_com_caractere_nulo_e_recusado():
    with pytest.raises(RecusaIngestao) as excinfo:
        validar_metadados(dict(MINIMO, tema='So\x00lo'))
    assert 'tema com caractere nulo' in excinfo.value.erros


def test_texto_acima_do_limite_e_recusado():
    with pytest.raises(RecusaIngestao) as excinfo:
        validar_metadados(dict(MINIMO, nome='x' * 201))
    assert 'nome acima de 200 caracteres' in excinfo.value.erros[0]


# Caminho infeliz: atributos

def test_nome_de_coluna_vazio_e_recusado():
    previa = previa_sintetica(['codigo', '   '], [{'codigo': 'A1', '   ': 1}])
    with pytest.raises(RecusaIngestao) as excinfo:
        atributos_da_previa(previa)
    assert excinfo.value.erros == ['coluna 2: nome vazio']


def test_nome_de_coluna_com_caractere_de_controle_e_recusado():
    previa = previa_sintetica(['a\x01b'], [{'a\x01b': 1}])
    with pytest.raises(RecusaIngestao) as excinfo:
        atributos_da_previa(previa)
    assert 'caractere de controle' in excinfo.value.erros[0]


def test_nome_de_coluna_acima_do_limite_e_recusado():
    nome = 'c' * 101
    previa = previa_sintetica([nome], [{nome: 1}])
    with pytest.raises(RecusaIngestao) as excinfo:
        atributos_da_previa(previa)
    assert 'acima de 100 caracteres' in excinfo.value.erros[0]


def test_nome_de_coluna_repetido_e_recusado():
    previa = previa_sintetica(['codigo', 'codigo'], [{'codigo': 'A1'}])
    with pytest.raises(RecusaIngestao) as excinfo:
        atributos_da_previa(previa)
    assert excinfo.value.erros == ['coluna 2: nome repetido']


def test_nome_com_marcacao_nao_e_recusado_so_guardado():
    atributos = atributos_da_previa(previa_sintetica(['<script>x</script>'], [{'<script>x</script>': 'y'}]))
    assert atributos[0].nome == '<script>x</script>'


def test_zero_nao_e_ausente_nos_valores_do_atributo():
    atributo = atributos_da_previa(previa_sintetica(['area'], [{'area': 0}, {'area': None}]))[0]
    assert atributo.valores == (0, None)
    assert atributo.tipo == 'numero'


def test_erros_de_metadado_e_de_coluna_saem_juntos():
    previa = previa_sintetica(['codigo', 'codigo'], [{'codigo': 'A1'}])
    with pytest.raises(RecusaIngestao) as excinfo:
        montar_previa(previa, {'nome': 'x'})
    erros = excinfo.value.erros
    assert 'tema é obrigatório' in erros
    assert 'origem é obrigatório' in erros
    assert 'coluna 2: nome repetido' in erros


@pytest.mark.parametrize('data', ['20260502', '2026-W18-6', '2026-5-2', '2026-02-30', '２０２６-０５-０２', '٢٠٢٦-٠٥-٠٢'])
def test_data_fora_da_forma_exata_ou_do_calendario_e_recusada(data):
    # Achado 7: fromisoformat aceita 20260502 e 2026-W18-6; a forma AAAA-MM-DD vem antes do calendário.
    with pytest.raises(RecusaIngestao) as excinfo:
        validar_metadados(dict(MINIMO, data_coleta=data))
    assert 'data_coleta deve ser data AAAA-MM-DD' in excinfo.value.erros


def test_data_fora_do_formato_e_recusada_e_data_valida_aceita():
    with pytest.raises(RecusaIngestao) as excinfo:
        validar_metadados(dict(MINIMO, data_coleta='02/05/2026'))
    assert 'data_coleta deve ser data AAAA-MM-DD' in excinfo.value.erros
    assert validar_metadados(dict(MINIMO, data_coleta='2026-05-02')).opcionais['data_coleta'] == '2026-05-02'

