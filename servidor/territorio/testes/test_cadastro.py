"""A7 (R7): quem cria empresa, fazenda e sub-área; sem autocadastro."""

import smtplib
import threading

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from datetime import timedelta
from importlib import import_module

from django.db import IntegrityError, connections, transaction
from django.utils import timezone

from comum.models import EventoAuditoria
from identidade import email
from identidade.models import Pessoa
from permissao.models import Cargo, CargoPermissao, Concessao, Convite, Permissao
from permissao.cargo import gerenciar_cargo
from permissao.convite import convidar_por_cpf
from permissao.delegacao import conceder
from permissao.pode import pode
from territorio.cadastro import (
    arquivar, criar_empresa, criar_fazenda, criar_sub_area, desarquivar, efeitos_do_arquivamento, renomear_empresa,
    renomear_fazenda, renomear_sub_area,
)
from territorio.models import Empresa, Fazenda, NivelDivisao, SubArea
from territorio.niveis import definir_nivel

pytestmark = pytest.mark.django_db


def _contagens():
    return (Empresa.objects.count(), Cargo.objects.count(), Pessoa.objects.count(), Concessao.objects.count())


def test_plataforma_cria_empresa_cargos_e_o_primeiro_administrador_com_senha_temporaria(plataforma, cpf_novo, mailoutbox):
    empresa, administrador, temporaria = criar_empresa(plataforma, 'Empresa Nova', 'Ana Administradora', 'ana@exemplo.test', cpf_novo())
    assert Cargo.objects.filter(empresa=empresa).count() == 4
    assert administrador.empresa_origem == empresa
    assert administrador.deve_trocar_senha is True
    assert administrador.check_password(temporaria)
    concessao = Concessao.objects.get(pessoa=administrador)
    assert (concessao.cargo.base, concessao.empresa, concessao.fazenda, concessao.sub_area) == ('administrador', empresa, None, None)
    assert concessao.concedida_por == plataforma
    assert empresa.titular == administrador
    assert len(mailoutbox) == 1
    assert temporaria in mailoutbox[0].body
    assert pode(Pessoa.objects.get(pk=administrador.pk), 'criar_fazenda', empresa) is True


def test_administrador_de_empresa_nao_cria_empresa(cenario, fabrica_pessoa, conceder_direto, cpf_novo, mailoutbox):
    admin = fabrica_pessoa('Admin da X')
    conceder_direto(admin, cenario.cargos_x['administrador'], cenario.x)
    antes = _contagens()
    cpf = cpf_novo()
    with pytest.raises(PermissionDenied):
        criar_empresa(admin, 'Empresa Intrusa', 'Ivo Intruso', 'ivo@exemplo.test', cpf)
    assert _contagens() == antes
    assert mailoutbox == []


def test_cargo_personalizado_com_criar_empresa_nao_cria_empresa(cenario, fabrica_pessoa, conceder_direto, cpf_novo):
    cargo = Cargo.objects.create(empresa=cenario.x, nome='Quase plataforma', base='administrador')
    CargoPermissao.objects.create(cargo=cargo, permissao_id='criar_empresa')
    pessoa = fabrica_pessoa('Quase Plataforma')
    conceder_direto(pessoa, cargo, cenario.x)
    cpf = cpf_novo()
    with pytest.raises(PermissionDenied):
        criar_empresa(pessoa, 'Empresa Intrusa', 'Ivo Intruso', 'ivo@exemplo.test', cpf)


def test_smtp_que_falha_nao_desfaz_a_empresa_criada(plataforma, cpf_novo, monkeypatch):
    # O e-mail sai depois do commit (T5.5a 4 e 5): falha de SMTP vira log, a criação fica de pé.
    def falha(*_):
        raise smtplib.SMTPException('fora do ar')

    monkeypatch.setattr(email.EmailMessage, 'send', falha)
    empresa, _, _ = criar_empresa(plataforma, 'Empresa Nova', 'Ana Administradora', 'ana@exemplo.test', cpf_novo())
    assert Empresa.objects.filter(pk=empresa.pk).exists()


def test_cpf_do_administrador_ja_cadastrado_levanta_cpf_duplicado_e_nada_fica(plataforma, cpf_novo):
    cpf = cpf_novo()
    criar_empresa(plataforma, 'Primeira', 'Ana Administradora', 'ana@exemplo.test', cpf)
    antes = _contagens()
    with pytest.raises(ValidationError) as erro:
        criar_empresa(plataforma, 'Segunda', 'Ana Outra', 'ana2@exemplo.test', cpf)
    assert erro.value.code == 'cpf_duplicado'
    assert _contagens() == antes


def test_administrador_cria_fazenda_na_propria_empresa_e_nao_na_alheia(cenario, fabrica_pessoa, conceder_direto):
    admin = fabrica_pessoa('Admin da X')
    conceder_direto(admin, cenario.cargos_x['administrador'], cenario.x)
    assert criar_fazenda(admin, cenario.x, 'Nova').empresa == cenario.x
    with pytest.raises(PermissionDenied):
        criar_fazenda(admin, cenario.y, 'Invasora')
    assert not Fazenda.objects.filter(nome='Invasora').exists()


def test_curador_tecnico_e_usuario_nao_criam_fazenda(cenario, fabrica_pessoa, conceder_direto):
    for base in ('curador', 'tecnico', 'usuario'):
        pessoa = fabrica_pessoa(f'Pessoa {base}')
        conceder_direto(pessoa, cenario.cargos_x[base], cenario.x)
        with pytest.raises(PermissionDenied):
            criar_fazenda(pessoa, cenario.x, f'Proibida {base}')


def test_plataforma_cria_fazenda_em_qualquer_empresa(cenario, plataforma):
    assert criar_fazenda(plataforma, cenario.y, 'Da Plataforma').empresa == cenario.y


def test_sub_area_em_ate_tres_niveis_e_o_quarto_e_recusado(cenario, fabrica_pessoa, conceder_direto):
    admin = fabrica_pessoa('Admin da X')
    conceder_direto(admin, cenario.cargos_x['administrador'], cenario.f2)
    gleba = criar_sub_area(admin, cenario.f2, 'Gleba')
    talhao = criar_sub_area(admin, cenario.f2, 'Talhão', pai=SubArea.objects.get(pk=gleba.pk))
    folha = criar_sub_area(admin, cenario.f2, 'Folha', pai=SubArea.objects.get(pk=talhao.pk))
    assert (gleba.nivel, talhao.nivel, folha.nivel) == (1, 2, 3)
    pai = SubArea.objects.get(pk=folha.pk)
    with pytest.raises(ValidationError) as erro:
        criar_sub_area(admin, cenario.f2, 'Quarto', pai=pai)
    assert erro.value.code == 'nivel_maximo'


def test_sub_area_criada_ja_vale_para_quem_tem_concessao_no_ancestral(cenario, fabrica_pessoa, conceder_direto):
    admin = fabrica_pessoa('Admin da X')
    conceder_direto(admin, cenario.cargos_x['administrador'], cenario.f2)
    usuario = fabrica_pessoa('Usuario da Gleba')
    gleba = criar_sub_area(admin, cenario.f2, 'Gleba')
    conceder_direto(usuario, cenario.cargos_x['usuario'], gleba)
    talhao = criar_sub_area(admin, cenario.f2, 'Talhão', pai=SubArea.objects.get(pk=gleba.pk))
    assert talhao.caminho == f'/{gleba.pk}/'
    assert pode(usuario, 'ver', talhao) is True


def test_pai_de_outra_fazenda_levanta_pai_de_outra_fazenda_e_nada_fica(cenario, fabrica_pessoa, conceder_direto):
    admin = fabrica_pessoa('Admin da X')
    conceder_direto(admin, cenario.cargos_x['administrador'], cenario.x)
    pai = SubArea.objects.get(pk=cenario.g1.pk)  # sub-área da F1
    antes = SubArea.objects.count()
    with pytest.raises(ValidationError) as erro:
        criar_sub_area(admin, cenario.f2, 'Filha enviesada', pai=pai)
    assert erro.value.code == 'pai_de_outra_fazenda'
    assert SubArea.objects.count() == antes


def test_sub_area_so_com_permissao_no_escopo(cenario, fabrica_pessoa, conceder_direto):
    admin_da_f1 = fabrica_pessoa('Admin da F1')
    conceder_direto(admin_da_f1, cenario.cargos_x['administrador'], cenario.f1)
    usuario = fabrica_pessoa('Usuario')
    conceder_direto(usuario, cenario.cargos_x['usuario'], cenario.f1)
    assert criar_sub_area(admin_da_f1, cenario.f1, 'Nova').fazenda == cenario.f1
    with pytest.raises(PermissionDenied):
        criar_sub_area(admin_da_f1, cenario.f2, 'Em outra fazenda')
    with pytest.raises(PermissionDenied):
        criar_sub_area(usuario, cenario.f1, 'Proibida')


def test_pessoa_sem_a_marca_nao_cria_empresa_nao_ha_autocadastro(cenario, fabrica_pessoa):
    quem = fabrica_pessoa('Qualquer Pessoa')
    with pytest.raises(PermissionDenied):
        criar_empresa(quem, 'Autocadastro', 'Quem Quer', 'q@exemplo.test', '12345678909')


# --- 003 R9, R10, R11: nome válido, renomear, arquivar e desarquivar ---


@pytest.fixture
def admin_x(cenario, fabrica_pessoa, conceder_direto):
    pessoa = fabrica_pessoa('Admin da X')
    conceder_direto(pessoa, cenario.cargos_x['administrador'], cenario.x)
    return pessoa


def _eventos(acao):
    return list(EventoAuditoria.objects.filter(acao=acao).order_by('pk'))


def _convite(cenario, pessoa, empresa=None, fazenda=None, sub_area=None, **campos):
    return Convite.objects.create(
        pessoa=pessoa, convidado_por=pessoa, cargo=cenario.cargos_x['usuario'], empresa=empresa or cenario.x,
        fazenda=fazenda, sub_area=sub_area, empresa_nome='Empresa X', cargo_nome='Usuário',
        expira_em=timezone.now() + timedelta(days=3), **campos,
    )


@pytest.mark.parametrize('nome', ['', '   ', 'x' * 201])
def test_nome_invalido_e_recusado_na_funcao_ao_criar_e_ao_renomear(cenario, plataforma, admin_x, cpf_novo, nome):
    gleba = SubArea.objects.get(pk=cenario.g1.pk)
    for chamada in (
        lambda: criar_empresa(plataforma, nome, 'Ana', 'ana@exemplo.test', cpf_novo()),
        lambda: criar_fazenda(admin_x, cenario.x, nome),
        lambda: criar_sub_area(admin_x, cenario.f2, nome),
        lambda: renomear_empresa(admin_x, cenario.x, nome),
        lambda: renomear_fazenda(admin_x, cenario.f1, nome),
        lambda: renomear_sub_area(admin_x, gleba, nome),
    ):
        with pytest.raises(ValidationError) as erro:
            chamada()
        assert erro.value.code == 'nome_invalido'
    assert Empresa.objects.get(pk=cenario.x.pk).nome == 'Empresa X'


def test_criar_empresa_grava_os_niveis_1_e_2_e_nao_o_3(plataforma, cpf_novo):
    empresa, _, _ = criar_empresa(plataforma, 'Nova', 'Ana', 'ana@exemplo.test', cpf_novo())
    assert dict(NivelDivisao.objects.filter(empresa=empresa).values_list('nivel', 'nome')) == {1: 'Gleba', 2: 'Talhão'}


def test_renomear_grava_nome_novo_e_auditoria_com_o_antigo_e_o_novo(cenario, admin_x):
    renomear_fazenda(admin_x, cenario.f1, '  F1 Nova  ')
    renomear_empresa(admin_x, cenario.x, 'X Nova')
    renomear_sub_area(admin_x, SubArea.objects.get(pk=cenario.g1.pk), 'G1 Nova')
    assert [Fazenda.objects.get(pk=cenario.f1.pk).nome, Empresa.objects.get(pk=cenario.x.pk).nome] == ['F1 Nova', 'X Nova']
    (evento,) = _eventos('fazenda_renomeada')
    assert (evento.pessoa_id, evento.alvo_id, evento.empresa_id) == (admin_x.pk, cenario.f1.pk, cenario.x.pk)
    assert evento.detalhes == {'nome_antigo': 'F1', 'nome_novo': 'F1 Nova'}
    assert len(_eventos('empresa_renomeada')) == len(_eventos('sub_area_renomeada')) == 1


def test_renomear_so_com_a_acao_no_escopo(cenario, fabrica_pessoa, conceder_direto, admin_x):
    for base in ('curador', 'tecnico', 'usuario'):
        pessoa = fabrica_pessoa(f'Pessoa {base}')
        conceder_direto(pessoa, cenario.cargos_x[base], cenario.x)
        with pytest.raises(PermissionDenied):
            renomear_fazenda(pessoa, cenario.f1, 'Invasora')
    with pytest.raises(PermissionDenied):
        renomear_fazenda(admin_x, cenario.fy, 'De outra empresa')
    assert Fazenda.objects.get(pk=cenario.f1.pk).nome == 'F1'
    assert not _eventos('fazenda_renomeada')


def test_arquivar_fazenda_arquiva_as_sub_areas_com_o_mesmo_ato_e_deixa_o_resto(cenario, admin_x):
    arquivar(admin_x, cenario.f1)
    f1 = Fazenda.objects.get(pk=cenario.f1.pk)
    ato = f1.arquivamento
    assert f1.arquivada_em is not None
    assert f1.arquivada_por_id == admin_x.pk
    assert set(SubArea.objects.filter(arquivamento=ato).values_list('nome', flat=True)) == {'G1', 'T1', 'G2'}
    assert Fazenda.objects.get(pk=cenario.f2.pk).arquivada_em is None
    assert Empresa.objects.get(pk=cenario.x.pk).arquivada_em is None
    assert Concessao.objects.filter(empresa=cenario.x).exists()  # concessões intactas
    (evento,) = _eventos('territorio_arquivado')
    assert evento.detalhes == {'arquivamento': str(ato), 'convites_invalidados': []}


def test_arquivar_empresa_arquiva_fazendas_e_sub_areas(cenario, plataforma):
    arquivar(plataforma, cenario.x)
    assert not Fazenda.objects.filter(empresa=cenario.x, arquivada_em__isnull=True).exists()
    assert not SubArea.objects.filter(empresa=cenario.x, arquivada_em__isnull=True).exists()
    assert Fazenda.objects.get(pk=cenario.fy.pk).arquivada_em is None


def test_arquivar_sub_area_arquiva_as_descendentes_e_nao_a_irma(cenario, admin_x):
    arquivar(admin_x, SubArea.objects.get(pk=cenario.g1.pk))
    arquivadas = set(SubArea.objects.filter(arquivada_em__isnull=False).values_list('nome', flat=True))
    assert arquivadas == {'G1', 'T1'}


def test_escrita_no_escopo_arquivado_e_negada_inclusive_para_a_plataforma(cenario, admin_x, plataforma):
    arquivar(admin_x, cenario.f1)
    for quem in (admin_x, plataforma):
        with pytest.raises(PermissionDenied):
            renomear_fazenda(quem, cenario.f1, 'Nova')
        with pytest.raises(PermissionDenied):
            criar_sub_area(quem, cenario.f1, 'Nova')
        with pytest.raises(PermissionDenied):
            arquivar(quem, cenario.f1)


def test_empresa_arquivada_nao_recebe_fazenda_nova(cenario, plataforma, admin_x):
    arquivar(plataforma, cenario.x)
    with pytest.raises(PermissionDenied):
        criar_fazenda(admin_x, cenario.x, 'Nasce arquivada?')
    assert not Fazenda.objects.filter(nome='Nasce arquivada?').exists()


def test_curador_tecnico_e_usuario_nao_arquivam_nem_desarquivam(cenario, fabrica_pessoa, conceder_direto, admin_x):
    for base in ('curador', 'tecnico', 'usuario'):
        pessoa = fabrica_pessoa(f'Pessoa {base}')
        conceder_direto(pessoa, cenario.cargos_x[base], cenario.x)
        with pytest.raises(PermissionDenied):
            arquivar(pessoa, cenario.f1)
        with pytest.raises(PermissionDenied):
            desarquivar(pessoa, cenario.f1)
    arquivar(admin_x, cenario.f1)
    arquivada = Fazenda.objects.get(pk=cenario.f1.pk)
    with pytest.raises(PermissionDenied):
        desarquivar(pessoa, arquivada)
    assert Fazenda.objects.get(pk=cenario.f1.pk).arquivada_em is not None


def test_administrador_de_outra_empresa_nao_arquiva(cenario, fabrica_pessoa, conceder_direto):
    estranho = fabrica_pessoa('Admin da Y')
    conceder_direto(estranho, cenario.cargos_y['administrador'], cenario.y)
    with pytest.raises(PermissionDenied):
        arquivar(estranho, cenario.f1)
    assert Fazenda.objects.get(pk=cenario.f1.pk).arquivada_em is None


def test_desarquivar_restaura_so_os_filhos_do_mesmo_ato(cenario, admin_x, plataforma):
    arquivar(admin_x, SubArea.objects.get(pk=cenario.g2.pk))  # ato A, antes
    arquivar(plataforma, cenario.f1)  # ato B: G1 e T1; G2 segue com o ato A
    desarquivar(plataforma, Fazenda.objects.get(pk=cenario.f1.pk))
    assert Fazenda.objects.get(pk=cenario.f1.pk).arquivada_em is None
    restantes = set(SubArea.objects.filter(arquivada_em__isnull=False).values_list('nome', flat=True))
    assert restantes == {'G2'}
    assert len(_eventos('territorio_desarquivado')) == 1


def test_desarquivar_filho_com_ancestral_arquivado_e_recusado(cenario, plataforma):
    arquivar(plataforma, cenario.x)
    filha = Fazenda.objects.get(pk=cenario.f1.pk)
    with pytest.raises(ValidationError) as erro:
        desarquivar(plataforma, filha)
    assert erro.value.code == 'ancestral_arquivado'
    assert Fazenda.objects.get(pk=cenario.f1.pk).arquivada_em is not None
    desarquivar(plataforma, Empresa.objects.get(pk=cenario.x.pk))
    assert not Fazenda.objects.filter(empresa=cenario.x, arquivada_em__isnull=False).exists()


def test_desarquivar_o_que_nao_esta_arquivado_e_recusado(cenario, admin_x):
    with pytest.raises(ValidationError) as erro:
        desarquivar(admin_x, cenario.f1)
    assert erro.value.code == 'nao_arquivado'


def test_desarquivar_vale_para_o_administrador_mesmo_com_o_escopo_arquivado(cenario, admin_x):
    arquivar(admin_x, cenario.f1)
    desarquivar(admin_x, Fazenda.objects.get(pk=cenario.f1.pk))
    assert pode(admin_x, 'criar_sub_area', cenario.f1) is True


def test_arquivar_invalida_convites_pendentes_do_escopo_e_eles_nao_voltam(cenario, admin_x, fabrica_pessoa):
    convidada = fabrica_pessoa('Convidada')
    da_f1 = _convite(cenario, convidada, fazenda=cenario.f1)
    da_sub_area = _convite(cenario, convidada, fazenda=cenario.f1, sub_area=cenario.t1)
    da_f2 = _convite(cenario, convidada, fazenda=cenario.f2)
    ja_aceito = _convite(cenario, convidada, fazenda=cenario.f1, aceito_em=timezone.now())
    arquivar(admin_x, cenario.f1)
    cancelados = set(Convite.objects.filter(cancelado_em__isnull=False).values_list('pk', flat=True))
    assert cancelados == {da_f1.pk, da_sub_area.pk}
    assert Convite.objects.get(pk=da_f2.pk).cancelado_em is None
    assert Convite.objects.get(pk=ja_aceito.pk).cancelado_em is None
    (evento,) = _eventos('territorio_arquivado')
    assert evento.detalhes['convites_invalidados'] == sorted([da_f1.pk, da_sub_area.pk])
    desarquivar(admin_x, Fazenda.objects.get(pk=cenario.f1.pk))
    assert Convite.objects.get(pk=da_f1.pk).cancelado_em is not None


def test_arquivar_empresa_invalida_o_convite_da_empresa_inteira(cenario, plataforma, fabrica_pessoa):
    convite = _convite(cenario, fabrica_pessoa('Convidada'))
    arquivar(plataforma, cenario.x)
    assert Convite.objects.get(pk=convite.pk).cancelado_em is not None


def test_criar_fazenda_depois_do_arquivamento_nao_nasce_ativa_sob_pai_arquivado(cenario, admin_x, plataforma):
    # Ordem que a trava garante: a criação concorrente espera o arquivamento e depois lê o estado gravado.
    # A corrida com duas conexões fica a cargo do job de integração; aqui vale o resultado da ordem.
    arquivar(plataforma, cenario.x)
    empresa = Empresa.objects.get(pk=cenario.x.pk)
    with pytest.raises(PermissionDenied):
        criar_fazenda(admin_x, empresa, 'Atrasada')
    assert not Fazenda.objects.filter(nome='Atrasada').exists()
    assert not Fazenda.objects.filter(empresa=cenario.x, arquivada_em__isnull=True).exists()


def test_arquivamento_incoerente_e_recusado_pelo_banco(cenario):
    agora = timezone.now()
    with pytest.raises(IntegrityError), transaction.atomic():
        Fazenda.objects.filter(pk=cenario.f1.pk).update(arquivada_em=agora)


def test_efeitos_do_arquivamento_contam_o_que_o_ato_atinge_sem_arquivar(cenario, fabrica_pessoa):
    from territorio.cadastro import efeitos_do_arquivamento

    _convite(cenario, fabrica_pessoa('Convidada'), fazenda=cenario.f1)
    assert efeitos_do_arquivamento(Fazenda.objects.get(pk=cenario.f1.pk)) == (0, 3, 1)
    assert efeitos_do_arquivamento(Empresa.objects.get(pk=cenario.x.pk)) == (2, 3, 1)
    assert efeitos_do_arquivamento(SubArea.objects.get(pk=cenario.g1.pk)) == (0, 1, 0)
    assert Fazenda.objects.get(pk=cenario.f1.pk).arquivada_em is None  # só mede


# --- corrida real entre duas conexões: a criação espera o arquivamento e depois lê o estado gravado (R11) ---




def _criar_enquanto_arquiva(alvo_a_arquivar, solicitante, criar):
    """Arquiva `alvo_a_arquivar` numa transação aberta, dispara `criar` noutra conexão e confere que ela espera a
    primeira terminar; devolve o erro que a criação levantou depois do commit."""
    resultado = {}

    def tarefa():
        try:
            criar()
            resultado['erro'] = None
        except Exception as erro:  # noqa: BLE001 - o teste confere o tipo logo abaixo
            resultado['erro'] = erro
        finally:
            connections.close_all()

    with transaction.atomic():
        arquivar(solicitante, alvo_a_arquivar)
        fio = threading.Thread(target=tarefa)
        fio.start()
        fio.join(timeout=1.5)
        esperou = fio.is_alive()
    fio.join(timeout=15)
    return esperou, resultado['erro']


@pytest.fixture
def catalogo_da_corrida(transactional_db):
    # O teste transacional esvazia o catálogo: recarrega o que as migrações 0001 e 0007 gravam, antes do `cenario`.
    for migracao in ('0001_initial', '0007_acoes_territorio'):
        for codigo, descricao, delegavel in import_module(f'permissao.migrations.{migracao}').ACOES:
            Permissao.objects.get_or_create(codigo=codigo, defaults={'descricao': descricao, 'delegavel': delegavel})


@pytest.mark.django_db(transaction=True)
def test_filha_criada_enquanto_o_pai_e_arquivado_em_outra_conexao_espera_e_e_negada(catalogo_da_corrida, cenario, plataforma):
    fazenda = Fazenda.objects.get(pk=cenario.f1.pk)
    pai = SubArea.objects.get(pk=cenario.g1.pk)
    outra = Pessoa.objects.get(pk=plataforma.pk)
    esperou, erro = _criar_enquanto_arquiva(pai, plataforma, lambda: criar_sub_area(outra, fazenda, 'Filha da corrida', pai=pai))
    assert esperou
    assert isinstance(erro, PermissionDenied)
    assert not SubArea.objects.filter(nome='Filha da corrida').exists()


@pytest.mark.django_db(transaction=True)
def test_fazenda_criada_enquanto_a_empresa_e_arquivada_em_outra_conexao_espera_e_e_negada(catalogo_da_corrida, cenario, plataforma):
    empresa = Empresa.objects.get(pk=cenario.x.pk)
    outra = Pessoa.objects.get(pk=plataforma.pk)
    esperou, erro = _criar_enquanto_arquiva(empresa, plataforma, lambda: criar_fazenda(outra, empresa, 'Fazenda da corrida'))
    assert esperou
    assert isinstance(erro, PermissionDenied)
    assert not Fazenda.objects.filter(nome='Fazenda da corrida').exists()


def test_renomear_audita_o_nome_gravado_e_nao_o_que_a_instancia_trazia(cenario, admin_x):
    velha = Fazenda.objects.get(pk=cenario.f1.pk)  # lida antes da outra renomeação
    renomear_fazenda(admin_x, Fazenda.objects.get(pk=cenario.f1.pk), 'F1 Primeira')
    renomear_fazenda(admin_x, velha, 'F1 Segunda')
    primeira, segunda = _eventos('fazenda_renomeada')
    assert primeira.detalhes == {'nome_antigo': 'F1', 'nome_novo': 'F1 Primeira'}
    assert segunda.detalhes == {'nome_antigo': 'F1 Primeira', 'nome_novo': 'F1 Segunda'}


@pytest.mark.parametrize('nome', ['', '   ', 'x' * 201])
def test_nome_do_administrador_invalido_e_recusado_e_nada_fica(plataforma, cpf_novo, nome):
    antes = _contagens()
    with pytest.raises(ValidationError) as erro:
        criar_empresa(plataforma, 'Empresa Nova', nome, 'ana@exemplo.test', cpf_novo())
    assert erro.value.code == 'nome_invalido'
    assert _contagens() == antes


@pytest.mark.django_db(transaction=True)
def test_convite_criado_enquanto_a_fazenda_e_arquivada_em_outra_conexao_espera_e_e_negado(catalogo_da_corrida, cenario, plataforma, cpf_novo):
    fazenda = Fazenda.objects.get(pk=cenario.f1.pk)
    outra = Pessoa.objects.get(pk=plataforma.pk)
    cargo = cenario.cargos_x['usuario']
    cpf = cpf_novo()
    esperou, erro = _criar_enquanto_arquiva(
        fazenda, plataforma, lambda: convidar_por_cpf(outra, 'Convidada', 'convidada@exemplo.test', cpf, cargo, fazenda)
    )
    assert esperou
    assert isinstance(erro, PermissionDenied)
    assert not Convite.objects.filter(fazenda=fazenda).exists()
    assert not Pessoa.objects.filter(email='convidada@exemplo.test').exists()


def test_convidar_e_conceder_em_escopo_arquivado_sao_negados_ate_para_a_plataforma(cenario, plataforma, fabrica_pessoa, cpf_novo):
    arquivar(plataforma, cenario.f1)
    fazenda = Fazenda.objects.get(pk=cenario.f1.pk)
    alvo = fabrica_pessoa('Alvo')
    with pytest.raises(PermissionDenied):
        convidar_por_cpf(plataforma, 'Nova', 'nova@exemplo.test', cpf_novo(), cenario.cargos_x['usuario'], fazenda)
    with pytest.raises(PermissionDenied):
        conceder(plataforma, alvo, cenario.cargos_x['usuario'], fazenda)
    assert not Concessao.objects.filter(pessoa=alvo).exists()


@pytest.mark.django_db(transaction=True)
def test_nivel_definido_enquanto_a_empresa_e_arquivada_em_outra_conexao_espera_e_e_negado(catalogo_da_corrida, cenario, plataforma):

    empresa = Empresa.objects.get(pk=cenario.x.pk)
    outra = Pessoa.objects.get(pk=plataforma.pk)
    esperou, erro = _criar_enquanto_arquiva(empresa, plataforma, lambda: definir_nivel(outra, empresa, 1, 'Quadra'))
    assert esperou
    assert isinstance(erro, PermissionDenied)
    assert not NivelDivisao.objects.filter(empresa=empresa, nome='Quadra').exists()


@pytest.mark.django_db(transaction=True)
def test_cargo_gerenciado_enquanto_a_empresa_e_arquivada_em_outra_conexao_espera_e_e_negado(catalogo_da_corrida, cenario, plataforma):
    empresa = Empresa.objects.get(pk=cenario.x.pk)
    outra = Pessoa.objects.get(pk=plataforma.pk)
    esperou, erro = _criar_enquanto_arquiva(empresa, plataforma, lambda: gerenciar_cargo(outra, empresa, 'Tarde', ['ver'], base='usuario'))
    assert esperou
    assert isinstance(erro, PermissionDenied)
    assert not Cargo.objects.filter(nome='Tarde').exists()


def test_arquivar_nao_cancela_convite_ja_aceito_nem_recusado(cenario, plataforma, fabrica_pessoa):
    convidada = fabrica_pessoa('Convidada')
    aceito = _convite(cenario, convidada, fazenda=cenario.f1, aceito_em=timezone.now())
    recusado = _convite(cenario, convidada, fazenda=cenario.f1, recusado_em=timezone.now())
    pendente = _convite(cenario, convidada, fazenda=cenario.f1)
    arquivar(plataforma, cenario.f1)
    assert Convite.objects.get(pk=aceito.pk).cancelado_em is None
    assert Convite.objects.get(pk=recusado.pk).cancelado_em is None
    assert Convite.objects.get(pk=pendente.pk).cancelado_em is not None


# --- nome único entre irmãos ativos e confirmação versionada ---


def test_nome_repetido_no_mesmo_lugar_e_recusado_sem_diferenciar_maiuscula_e_arquivado_libera_o_nome(cenario, admin_x, plataforma):
    criar_fazenda(admin_x, cenario.x, 'Repetida')
    for nome in ('Repetida', 'repetida', '  REPETIDA  '):
        with pytest.raises(ValidationError) as erro:
            criar_fazenda(admin_x, cenario.x, nome)
        assert erro.value.code == 'nome_duplicado'
    assert Fazenda.objects.filter(empresa=cenario.x, nome__iexact='repetida').count() == 1
    arquivar(plataforma, Fazenda.objects.get(nome='Repetida'))
    assert criar_fazenda(admin_x, cenario.x, 'Repetida').arquivada_em is None


def test_mesmo_nome_em_empresas_ou_fazendas_diferentes_e_permitido(cenario, plataforma):
    criar_fazenda(plataforma, cenario.x, 'Comum')
    assert criar_fazenda(plataforma, cenario.y, 'Comum').empresa_id == cenario.y.pk
    um = criar_sub_area(plataforma, cenario.f1, 'Gleba Comum')
    outro = criar_sub_area(plataforma, cenario.f2, 'Gleba Comum')
    assert (um.fazenda_id, outro.fazenda_id) == (cenario.f1.pk, cenario.f2.pk)


def test_sub_area_raiz_repetida_e_recusada_e_filhas_de_pais_diferentes_podem_repetir(cenario, plataforma):
    criar_sub_area(plataforma, cenario.f2, 'Raiz')
    with pytest.raises(ValidationError) as erro:
        criar_sub_area(plataforma, cenario.f2, 'raiz')
    assert erro.value.code == 'nome_duplicado'
    a = criar_sub_area(plataforma, cenario.f2, 'A')
    b = criar_sub_area(plataforma, cenario.f2, 'B')
    criar_sub_area(plataforma, cenario.f2, 'Filha', pai=SubArea.objects.get(pk=a.pk))
    criar_sub_area(plataforma, cenario.f2, 'Filha', pai=SubArea.objects.get(pk=b.pk))
    with pytest.raises(ValidationError):
        criar_sub_area(plataforma, cenario.f2, 'Filha', pai=SubArea.objects.get(pk=a.pk))


def test_renomear_para_nome_de_irma_ativa_e_recusado_e_empresa_repetida_tambem(cenario, plataforma, cpf_novo):
    with pytest.raises(ValidationError) as erro:
        renomear_fazenda(plataforma, cenario.f1, 'f2')
    assert erro.value.code == 'nome_duplicado'
    assert Fazenda.objects.get(pk=cenario.f1.pk).nome == 'F1'
    with pytest.raises(ValidationError) as erro_empresa:
        criar_empresa(plataforma, 'empresa x', 'Ana', 'ana@exemplo.test', cpf_novo())
    assert erro_empresa.value.code == 'nome_duplicado'
    assert _contagens()[0] == 2  # só X e Y: a empresa repetida não ficou


def test_desarquivar_com_o_nome_ocupado_por_irma_ativa_e_recusado(cenario, plataforma):
    arquivar(plataforma, cenario.f1)
    criar_fazenda(plataforma, cenario.x, 'F1')  # o nome ficou livre com a F1 arquivada
    with pytest.raises(ValidationError) as erro:
        desarquivar(plataforma, Fazenda.objects.get(pk=cenario.f1.pk))
    assert erro.value.code == 'nome_duplicado'
    assert Fazenda.objects.get(pk=cenario.f1.pk).arquivada_em is not None


def test_arquivar_com_efeitos_desatualizados_levanta_efeitos_mudaram_e_nada_muda(cenario, plataforma):
    esperados = efeitos_do_arquivamento(Fazenda.objects.get(pk=cenario.f1.pk))
    SubArea.objects.create(empresa=cenario.x, fazenda=cenario.f1, nivel=1, nome='Nova entre a tela e o ato')
    with pytest.raises(ValidationError) as erro:
        arquivar(plataforma, Fazenda.objects.get(pk=cenario.f1.pk), efeitos_esperados=esperados)
    assert erro.value.code == 'efeitos_mudaram'
    assert Fazenda.objects.get(pk=cenario.f1.pk).arquivada_em is None
    assert not SubArea.objects.filter(arquivada_em__isnull=False).exists()
    arquivar(plataforma, Fazenda.objects.get(pk=cenario.f1.pk), efeitos_esperados=efeitos_do_arquivamento(Fazenda.objects.get(pk=cenario.f1.pk)))
    assert Fazenda.objects.get(pk=cenario.f1.pk).arquivada_em is not None
