"""A7 (R7): quem cria empresa, fazenda e sub-área; sem autocadastro."""

import smtplib

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from identidade import email
from identidade.models import Pessoa
from permissao.models import Cargo, CargoPermissao, Concessao
from permissao.pode import pode
from territorio.cadastro import criar_empresa, criar_fazenda, criar_sub_area
from territorio.models import Empresa, Fazenda, SubArea

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
    with pytest.raises(PermissionDenied):
        criar_empresa(admin, 'Empresa Intrusa', 'Ivo Intruso', 'ivo@exemplo.test', cpf_novo())
    assert _contagens() == antes
    assert mailoutbox == []


def test_cargo_personalizado_com_criar_empresa_nao_cria_empresa(cenario, fabrica_pessoa, conceder_direto, cpf_novo):
    cargo = Cargo.objects.create(empresa=cenario.x, nome='Quase plataforma', base='administrador')
    CargoPermissao.objects.create(cargo=cargo, permissao_id='criar_empresa')
    pessoa = fabrica_pessoa('Quase Plataforma')
    conceder_direto(pessoa, cargo, cenario.x)
    with pytest.raises(PermissionDenied):
        criar_empresa(pessoa, 'Empresa Intrusa', 'Ivo Intruso', 'ivo@exemplo.test', cpf_novo())


def test_smtp_que_falha_nao_deixa_empresa_cargo_pessoa_nem_concessao(plataforma, cpf_novo, monkeypatch):
    def falha(pessoa, senha):
        raise smtplib.SMTPException('fora do ar')

    monkeypatch.setattr(email, 'enviar_senha_temporaria', falha)
    antes = _contagens()
    with pytest.raises(smtplib.SMTPException):
        criar_empresa(plataforma, 'Empresa Nova', 'Ana Administradora', 'ana@exemplo.test', cpf_novo())
    assert _contagens() == antes


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
    with pytest.raises(ValidationError) as erro:
        criar_sub_area(admin, cenario.f2, 'Quarto', pai=SubArea.objects.get(pk=folha.pk))
    assert erro.value.code == 'nivel_maximo'


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
