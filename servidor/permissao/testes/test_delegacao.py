"""A8 (R8, R9, R10) e a revogação (R11, A10): quem concede e quem revoga o quê."""

import smtplib
import threading
from types import SimpleNamespace

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection

from identidade import email
from identidade.models import Pessoa
from permissao.delegacao import conceder, convidar, pode_conceder, revogar_concessao, transferir_titularidade
from permissao.models import Cargo, CargoPermissao, CategoriaDado, Concessao
from permissao.pode import pode
from territorio.models import Empresa

pytestmark = pytest.mark.django_db


def _cargo(empresa, nome, base, *acoes):
    cargo = Cargo.objects.create(empresa=empresa, nome=nome, base=base)
    CargoPermissao.objects.bulk_create(CargoPermissao(cargo=cargo, permissao_id=a) for a in acoes)
    return cargo


def _com(fabrica_pessoa, conceder_direto, cargo, escopo, nome='Quem Concede', categorias=()):
    pessoa = fabrica_pessoa(nome)
    conceder_direto(pessoa, cargo, escopo, categorias=categorias)
    return pessoa


def _recarregar(pessoa):
    return Pessoa.objects.get(pk=pessoa.pk)


@pytest.fixture
def alvo(fabrica_pessoa):
    return fabrica_pessoa('Pessoa Alvo')


# --- concessão: o Administrador (D043) ---


def test_administrador_concede_permissao_que_a_lista_do_proprio_cargo_nao_traz(alvo, cenario, fabrica_pessoa, conceder_direto):
    # Cargo de Administrador sem `publicar_camada` na lista: ainda assim concede cargo que a contém (D043).
    sem_publicar = _cargo(cenario.x, 'Admin enxuto', 'administrador', 'ver', 'convidar_pessoa')
    admin = _com(fabrica_pessoa, conceder_direto, sem_publicar, cenario.x)
    cargo = _cargo(cenario.x, 'Publicador', 'curador', 'ver', 'publicar_camada')
    concessao = conceder(admin, alvo, cargo, cenario.f1)
    assert concessao.concedida_por == admin
    assert pode(alvo, 'publicar_camada', cenario.f1) is True
    assert pode(admin, 'publicar_camada', cenario.f1) is False  # conceder não é exercer


def test_administrador_concede_acao_nao_delegavel_no_escopo(alvo, cenario, fabrica_pessoa, conceder_direto):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    aprovacao = _cargo(cenario.x, 'Aprovação cartográfica', 'curador', 'ver', 'tornar_revisao_vigente', 'aprovar_geometria')
    conceder(admin, alvo, aprovacao, cenario.f1)
    assert pode(alvo, 'tornar_revisao_vigente', cenario.f1) is True


def test_administrador_de_empresa_so_concede_dentro_da_empresa(alvo, cenario, fabrica_pessoa, conceder_direto):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    with pytest.raises(PermissionDenied):
        conceder(admin, alvo, cenario.cargos_y['usuario'], cenario.fy)
    with pytest.raises(PermissionDenied):
        conceder(admin, alvo, cenario.cargos_x['usuario'], cenario.y)
    with pytest.raises(PermissionDenied):  # cargo da empresa Y, escopo em X
        conceder(admin, alvo, cenario.cargos_y['usuario'], cenario.f1)
    assert Concessao.objects.filter(pessoa=alvo).count() == 0


def test_administrador_com_escopo_de_fazenda_nao_concede_na_irma(alvo, cenario, fabrica_pessoa, conceder_direto):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.f1)
    conceder(admin, alvo, cenario.cargos_x['usuario'], cenario.t1)
    with pytest.raises(PermissionDenied):
        conceder(admin, alvo, cenario.cargos_x['usuario'], cenario.f2)
    with pytest.raises(PermissionDenied):
        conceder(admin, alvo, cenario.cargos_x['usuario'], cenario.x)


def test_administrador_de_empresa_convida_outro_administrador_so_na_propria_empresa(alvo, cenario, fabrica_pessoa, conceder_direto):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    conceder(admin, alvo, cenario.cargos_x['administrador'], cenario.x)
    with pytest.raises(PermissionDenied):
        conceder(admin, alvo, cenario.cargos_y['administrador'], cenario.y)


def test_plataforma_concede_qualquer_cargo_em_qualquer_empresa(alvo, cenario, plataforma):
    conceder(plataforma, alvo, cenario.cargos_x['administrador'], cenario.x)
    conceder(plataforma, alvo, cenario.cargos_y['administrador'], cenario.y)
    assert Concessao.objects.filter(pessoa=alvo).count() == 2


# --- concessão: Curador, Técnico, "ninguém concede o que não tem" ---


def test_curador_concede_tecnico_e_usuario_mas_nao_curador_nem_administrador(alvo, cenario, fabrica_pessoa, conceder_direto):
    curador = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['curador'], cenario.f1)
    conceder(curador, alvo, cenario.cargos_x['tecnico'], cenario.f1)
    conceder(curador, alvo, cenario.cargos_x['usuario'], cenario.t1)
    for base in ('curador', 'administrador'):
        with pytest.raises(PermissionDenied):
            conceder(curador, alvo, cenario.cargos_x[base], cenario.f1)


def test_curador_nao_concede_tornar_revisao_vigente(alvo, cenario, fabrica_pessoa, conceder_direto):
    curador = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['curador'], cenario.f1)
    aprovacao = _cargo(cenario.x, 'Aprovação de técnico', 'tecnico', 'ver', 'tornar_revisao_vigente')
    with pytest.raises(PermissionDenied):
        conceder(curador, alvo, aprovacao, cenario.f1)


def test_nao_administrador_nao_repassa_acao_nao_delegavel_nem_quando_o_proprio_cargo_a_tem(alvo, cenario, fabrica_pessoa, conceder_direto):
    com_aprovacao = _cargo(cenario.x, 'Curador com aprovação', 'curador', 'ver', 'convidar_pessoa', 'tornar_revisao_vigente')
    quem = _com(fabrica_pessoa, conceder_direto, com_aprovacao, cenario.f1)
    aprovacao = _cargo(cenario.x, 'Aprovação de técnico', 'tecnico', 'ver', 'tornar_revisao_vigente')
    with pytest.raises(PermissionDenied):
        conceder(quem, alvo, aprovacao, cenario.f1)


def test_curador_nao_concede_permissao_que_o_proprio_cargo_nao_tem(alvo, cenario, fabrica_pessoa, conceder_direto):
    curador = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['curador'], cenario.f1)
    publicador = _cargo(cenario.x, 'Técnico publicador', 'tecnico', 'ver', 'publicar_camada')
    with pytest.raises(PermissionDenied):
        conceder(curador, alvo, publicador, cenario.f1)


def test_curador_nao_concede_fora_do_proprio_escopo(alvo, cenario, fabrica_pessoa, conceder_direto):
    curador = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['curador'], cenario.g1)
    conceder(curador, alvo, cenario.cargos_x['usuario'], cenario.t1)
    for escopo in (cenario.g2, cenario.f1, cenario.f2, cenario.x):
        with pytest.raises(PermissionDenied):
            conceder(curador, alvo, cenario.cargos_x['usuario'], escopo)


def test_tecnico_comum_nao_convida_ninguem(alvo, cenario, fabrica_pessoa, conceder_direto):
    tecnico = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['tecnico'], cenario.f1)
    with pytest.raises(PermissionDenied):
        conceder(tecnico, alvo, cenario.cargos_x['usuario'], cenario.f1)


def test_cargo_personalizado_de_nivel_tecnico_nao_convida_nivel_acima_nem_igual(alvo, cenario, fabrica_pessoa, conceder_direto):
    personalizado = _cargo(
        cenario.x, 'Técnico que convida', 'tecnico',
        'ver', 'baixar_pacote_offline', 'criar_registro_campo', 'convidar_pessoa',
    )  # fmt: skip
    tecnico = _com(fabrica_pessoa, conceder_direto, personalizado, cenario.f1)
    conceder(tecnico, alvo, cenario.cargos_x['usuario'], cenario.f1)
    for base in ('tecnico', 'curador', 'administrador'):
        with pytest.raises(PermissionDenied):
            conceder(tecnico, alvo, cenario.cargos_x[base], cenario.f1)


def test_nivel_menor_nao_concede_cargo_de_nivel_maior_mesmo_com_as_permissoes(alvo, cenario, fabrica_pessoa, conceder_direto):
    # Só o nível barra: a lista do cargo concedido cabe inteira na do cargo de quem concede.
    do_tecnico = _cargo(cenario.x, 'Técnico que convida', 'tecnico', 'ver', 'convidar_pessoa')
    do_curador = _cargo(cenario.x, 'Curador só leitura', 'curador', 'ver')
    quem = _com(fabrica_pessoa, conceder_direto, do_tecnico, cenario.f1)
    with pytest.raises(PermissionDenied):
        conceder(quem, alvo, do_curador, cenario.f1)


# --- categorias ---


def test_ninguem_concede_categoria_que_nao_tem(alvo, cenario, fabrica_pessoa, conceder_direto):
    solo = CategoriaDado.objects.create(empresa=cenario.x, nome='Solo')
    agua = CategoriaDado.objects.create(empresa=cenario.x, nome='Água')
    personalizado = _cargo(cenario.x, 'Técnico que convida', 'tecnico', 'ver', 'baixar_pacote_offline', 'convidar_pessoa')
    tecnico = _com(fabrica_pessoa, conceder_direto, personalizado, cenario.f1, categorias=[solo])
    conceder(tecnico, alvo, cenario.cargos_x['usuario'], cenario.f1, categorias=[solo])
    with pytest.raises(PermissionDenied):
        conceder(tecnico, alvo, cenario.cargos_x['usuario'], cenario.f1, categorias=[agua])
    with pytest.raises(PermissionDenied):
        conceder(tecnico, alvo, cenario.cargos_x['usuario'], cenario.f1, categorias=[solo, agua])


def test_curador_concede_categoria_a_tecnico_e_a_concessao_guarda(alvo, cenario, fabrica_pessoa, conceder_direto):
    solo = CategoriaDado.objects.create(empresa=cenario.x, nome='Solo')
    curador = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['curador'], cenario.f1)
    concessao = conceder(curador, alvo, cenario.cargos_x['tecnico'], cenario.f1, categorias=[solo])
    assert list(concessao.categorias.all()) == [solo]


def test_categoria_em_cargo_de_nivel_curador_e_recusada_pelo_banco_e_nada_fica(alvo, cenario, plataforma):
    solo = CategoriaDado.objects.create(empresa=cenario.x, nome='Solo')
    with pytest.raises(IntegrityError):
        conceder(plataforma, alvo, cenario.cargos_x['curador'], cenario.f1, categorias=[solo])
    assert Concessao.objects.filter(pessoa=alvo).count() == 0


# --- pode_conceder direto ---


def test_pode_conceder_nega_anonimo_e_pessoa_sem_concessao(cenario, fabrica_pessoa):
    proposta = Concessao(cargo=cenario.cargos_x['usuario'], empresa=cenario.x, fazenda=cenario.f1)
    assert pode_conceder(None, proposta) is False
    assert pode_conceder(fabrica_pessoa('Sem Nada'), proposta) is False


def test_as_regras_nao_se_somam_entre_concessoes_diferentes(alvo, cenario, fabrica_pessoa, conceder_direto):
    # Uma concessão traz o nível (curador em F1), a outra traz a permissão (publicar, num cargo de técnico em F1):
    # nenhuma sozinha concede o cargo "técnico publicador"; juntas não valem.
    publicador = _cargo(cenario.x, 'Técnico publicador', 'tecnico', 'ver', 'publicar_camada')
    quem = fabrica_pessoa('Duas Concessoes')
    conceder_direto(quem, cenario.cargos_x['curador'], cenario.f1)
    cargo_com_publicar = _cargo(cenario.x, 'Usuário publicador', 'usuario', 'publicar_camada', 'convidar_pessoa')
    conceder_direto(quem, cargo_com_publicar, cenario.f1)
    with pytest.raises(PermissionDenied):
        conceder(quem, alvo, publicador, cenario.f1)


# --- convite: pessoa nova ---


def test_convite_cria_a_pessoa_envia_a_senha_temporaria_e_concede(cenario, fabrica_pessoa, conceder_direto, cpf_novo, mailoutbox):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    pessoa, temporaria = convidar(
        admin, 'Beatriz Convidada', 'bia@exemplo.test', cpf_novo(), cenario.cargos_x['curador'], cenario.f1
    )
    assert pessoa.empresa_origem == cenario.x
    assert pessoa.deve_trocar_senha is True and pessoa.check_password(temporaria)
    assert len(mailoutbox) == 1 and temporaria in mailoutbox[0].body and mailoutbox[0].to == ['bia@exemplo.test']
    assert pode(_recarregar(pessoa), 'convidar_pessoa', cenario.f1) is True


def test_convite_negado_por_nivel_nao_cria_pessoa_nem_envia_email(cenario, fabrica_pessoa, conceder_direto, cpf_novo, mailoutbox):
    curador = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['curador'], cenario.f1)
    antes = Pessoa.objects.count()
    with pytest.raises(PermissionDenied):
        convidar(curador, 'Carlos Convidado', 'c@exemplo.test', cpf_novo(), cenario.cargos_x['curador'], cenario.f1)
    assert Pessoa.objects.count() == antes
    assert mailoutbox == []


def test_smtp_que_falha_desfaz_o_convite_inteiro(cenario, fabrica_pessoa, conceder_direto, cpf_novo, monkeypatch):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)

    def falha(pessoa, senha):
        raise smtplib.SMTPException('fora do ar')

    monkeypatch.setattr(email, 'enviar_senha_temporaria', falha)
    antes_pessoas, antes_concessoes = Pessoa.objects.count(), Concessao.objects.count()
    with pytest.raises(smtplib.SMTPException):
        convidar(admin, 'Davi Convidado', 'd@exemplo.test', cpf_novo(), cenario.cargos_x['usuario'], cenario.f1)
    assert (Pessoa.objects.count(), Concessao.objects.count()) == (antes_pessoas, antes_concessoes)


def test_convite_com_cpf_ja_cadastrado_levanta_cpf_duplicado(cenario, fabrica_pessoa, conceder_direto, cpf_novo):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    cpf = cpf_novo()
    convidar(admin, 'Eva Convidada', 'e@exemplo.test', cpf, cenario.cargos_x['usuario'], cenario.f1)
    with pytest.raises(ValidationError) as erro:
        convidar(admin, 'Eva de Novo', 'e2@exemplo.test', cpf, cenario.cargos_x['usuario'], cenario.f1)
    assert erro.value.code == 'cpf_duplicado'


# --- revogação (A10) ---


def _revogavel(cenario, fabrica_pessoa, conceder_direto, base='usuario', escopo=None):
    titular = fabrica_pessoa('Titular')
    return titular, conceder_direto(titular, cenario.cargos_x[base], escopo or cenario.f1)


def test_revogar_grava_quem_e_quando_e_a_requisicao_seguinte_e_negada(cenario, fabrica_pessoa, conceder_direto):
    curador = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['curador'], cenario.f1)
    titular, concessao = _revogavel(cenario, fabrica_pessoa, conceder_direto)
    assert pode(_recarregar(titular), 'ver', cenario.f1) is True
    revogar_concessao(curador, concessao)
    assert concessao.revogada_por == curador and concessao.revogada_em is not None
    assert pode(_recarregar(titular), 'ver', cenario.f1) is False


def test_so_o_nivel_acima_revoga(cenario, fabrica_pessoa, conceder_direto, plataforma):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x, 'Admin Um')
    curador = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['curador'], cenario.x, 'Curador Um')
    tecnico = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['tecnico'], cenario.x, 'Tecnico Um')
    _, de_admin = _revogavel(cenario, fabrica_pessoa, conceder_direto, 'administrador')
    _, de_curador = _revogavel(cenario, fabrica_pessoa, conceder_direto, 'curador')
    for quem, concessao in ((curador, de_admin), (curador, de_curador), (tecnico, de_curador)):
        with pytest.raises(PermissionDenied):
            revogar_concessao(quem, concessao)
    revogar_concessao(admin, de_curador)  # nível acima
    revogar_concessao(admin, de_admin)  # Administrador revoga Administrador (não titular)
    assert Concessao.objects.filter(revogada_em__isnull=False).count() == 2


# --- Administrador titular (R23) ---


@pytest.fixture
def titulares(cenario, fabrica_pessoa, conceder_direto):
    """Empresa X com titular e um segundo Administrador; as duas concessões são da empresa inteira."""
    titular = fabrica_pessoa('Titular da X')
    outro = fabrica_pessoa('Outro Admin da X')
    de_titular = conceder_direto(titular, cenario.cargos_x['administrador'], cenario.x)
    de_outro = conceder_direto(outro, cenario.cargos_x['administrador'], cenario.x)
    cenario.x.titular = titular
    cenario.x.save(update_fields=['titular'])
    return SimpleNamespace(titular=titular, outro=outro, de_titular=de_titular, de_outro=de_outro)


def test_administrador_comum_nao_revoga_o_titular_nem_a_plataforma(cenario, titulares, plataforma):
    for quem in (titulares.outro, plataforma):
        with pytest.raises(ValidationError) as erro:
            revogar_concessao(quem, titulares.de_titular)
        assert erro.value.code == 'titular_protegido'
    titulares.de_titular.refresh_from_db()
    assert titulares.de_titular.revogada_em is None


def test_titular_revoga_outro_administrador_e_o_outro_tambem_e_revogavel_pela_plataforma(cenario, titulares, plataforma):
    revogar_concessao(titulares.titular, titulares.de_outro)
    assert titulares.de_outro.revogada_em is not None
    de_novo = Concessao.objects.create(
        pessoa=titulares.outro, cargo=cenario.cargos_x['administrador'], empresa=cenario.x, concedida_por=plataforma
    )
    revogar_concessao(plataforma, de_novo)
    assert de_novo.revogada_em is not None


def test_outra_concessao_do_titular_e_revogavel(cenario, titulares, conceder_direto):
    de_usuario = conceder_direto(titulares.titular, cenario.cargos_x['usuario'], cenario.f1)
    revogar_concessao(titulares.outro, de_usuario)
    assert de_usuario.revogada_em is not None


def test_titular_transfere_o_titulo_e_a_protecao_acompanha(cenario, titulares):
    transferir_titularidade(titulares.titular, cenario.x, titulares.outro)
    assert cenario.x.titular == titulares.outro
    with pytest.raises(ValidationError) as erro:
        revogar_concessao(titulares.titular, titulares.de_outro)
    assert erro.value.code == 'titular_protegido'
    revogar_concessao(titulares.outro, titulares.de_titular)  # o antigo titular é Administrador comum
    assert titulares.de_titular.revogada_em is not None


def test_so_o_titular_ou_a_plataforma_transferem(cenario, titulares, plataforma, fabrica_pessoa, conceder_direto):
    terceiro = fabrica_pessoa('Terceiro Admin')
    conceder_direto(terceiro, cenario.cargos_x['administrador'], cenario.x)
    for quem in (titulares.outro, terceiro, None):
        with pytest.raises(PermissionDenied):
            transferir_titularidade(quem, cenario.x, terceiro)
    assert cenario.x.titular == titulares.titular
    transferir_titularidade(plataforma, cenario.x, terceiro)
    assert cenario.x.titular == terceiro


def test_novo_titular_precisa_ser_administrador_ativo_da_empresa_inteira(cenario, titulares, fabrica_pessoa, conceder_direto, plataforma):
    curador = fabrica_pessoa('Curador')
    conceder_direto(curador, cenario.cargos_x['curador'], cenario.x)
    de_fazenda = fabrica_pessoa('Admin da F1')
    conceder_direto(de_fazenda, cenario.cargos_x['administrador'], cenario.f1)
    de_y = fabrica_pessoa('Admin da Y')
    conceder_direto(de_y, cenario.cargos_y['administrador'], cenario.y)
    revogado = fabrica_pessoa('Admin revogado')
    concessao = conceder_direto(revogado, cenario.cargos_x['administrador'], cenario.x)
    revogar_concessao(plataforma, concessao)
    for candidato in (curador, de_fazenda, de_y, revogado):
        with pytest.raises(ValidationError) as erro:
            transferir_titularidade(titulares.titular, cenario.x, candidato)
        assert erro.value.code == 'titular_invalido'
    assert cenario.x.titular == titulares.titular


def test_revogar_fora_do_escopo_e_negado(cenario, fabrica_pessoa, conceder_direto):
    curador_de_f2 = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['curador'], cenario.f2)
    _, concessao = _revogavel(cenario, fabrica_pessoa, conceder_direto)
    with pytest.raises(PermissionDenied):
        revogar_concessao(curador_de_f2, concessao)
    concessao.refresh_from_db()
    assert concessao.revogada_em is None


def test_revogar_sem_a_permissao_revogar_acesso_e_negado(cenario, fabrica_pessoa, conceder_direto):
    sem_revogar = _cargo(cenario.x, 'Curador sem revogar', 'curador', 'ver', 'convidar_pessoa')
    quem = _com(fabrica_pessoa, conceder_direto, sem_revogar, cenario.f1)
    _, concessao = _revogavel(cenario, fabrica_pessoa, conceder_direto)
    with pytest.raises(PermissionDenied):
        revogar_concessao(quem, concessao)


def test_revogar_duas_vezes_levanta_concessao_ja_revogada(cenario, fabrica_pessoa, conceder_direto, plataforma):
    _, concessao = _revogavel(cenario, fabrica_pessoa, conceder_direto)
    revogar_concessao(plataforma, concessao)
    with pytest.raises(ValidationError) as erro:
        revogar_concessao(plataforma, concessao)
    assert erro.value.code == 'concessao_ja_revogada'


def test_anonimo_nao_revoga(cenario, fabrica_pessoa, conceder_direto):
    _, concessao = _revogavel(cenario, fabrica_pessoa, conceder_direto)
    with pytest.raises(PermissionDenied):
        revogar_concessao(None, concessao)


# Transacional (como o teste abaixo): a plataforma transfere e revoga, para não depender do catálogo.
@pytest.mark.django_db(transaction=True)
def test_transferir_e_revogar_ao_mesmo_tempo_nunca_deixam_titular_sem_concessao(fabrica_pessoa, conceder_direto, plataforma):
    empresa = Empresa.objects.create(nome='Empresa da transferência')
    cargo = Cargo.objects.create(empresa=empresa, nome='Administrador', base='administrador')
    titular, outro = fabrica_pessoa('Titular'), fabrica_pessoa('Outro Admin')
    conceder_direto(titular, cargo, empresa)
    de_outro = conceder_direto(outro, cargo, empresa)
    for _ in range(15):
        Concessao.objects.filter(pk=de_outro.pk).update(revogada_em=None, revogada_por=None)
        Empresa.objects.filter(pk=empresa.pk).update(titular=titular)
        largada = threading.Barrier(2)

        def correr(funcao):
            largada.wait()
            try:
                funcao()
            except (ValidationError, PermissionDenied):
                pass  # a recusa é um desfecho válido da corrida
            finally:
                connection.close()

        fios = [
            threading.Thread(target=correr, args=(lambda: transferir_titularidade(plataforma, empresa, outro),)),
            threading.Thread(target=correr, args=(lambda: revogar_concessao(plataforma, Concessao.objects.get(pk=de_outro.pk)),)),
        ]
        for fio in fios:
            fio.start()
        for fio in fios:
            fio.join()
        empresa.refresh_from_db()
        de_outro.refresh_from_db()
        # Titular com a concessão revogada é o estado proibido (R23).
        assert not (empresa.titular_id == outro.pk and de_outro.revogada_em is not None)


# Transacional: o teste esvazia as tabelas ao fim, inclusive o catálogo da migração; por isso não usa `cenario`
# (que precisa do catálogo) e a revogação é feita pelo Administrador da plataforma, que não consulta cargos.
@pytest.mark.django_db(transaction=True)
def test_duas_revogacoes_ao_mesmo_tempo_so_uma_vence(fabrica_pessoa, conceder_direto, plataforma):
    empresa = Empresa.objects.create(nome='Empresa da corrida')
    cargo = Cargo.objects.create(empresa=empresa, nome='Usuário', base='usuario')
    concessao = conceder_direto(fabrica_pessoa('Titular'), cargo, empresa)
    resultados = []
    largada = threading.Barrier(2)

    def correr():
        largada.wait()
        try:
            revogar_concessao(plataforma, Concessao.objects.get(pk=concessao.pk))
            resultados.append('ok')
        except ValidationError as erro:
            resultados.append(erro.code)
        finally:
            connection.close()

    fios = [threading.Thread(target=correr) for _ in range(2)]
    for fio in fios:
        fio.start()
    for fio in fios:
        fio.join()
    assert sorted(resultados) == ['concessao_ja_revogada', 'ok']

