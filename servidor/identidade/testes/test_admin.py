"""Painel de pessoas (T5.2): convite pelo serviço, lista só do escopo e redefinição com a regra do R5."""

from django.contrib.messages import get_messages

from identidade import cpf as modulo_cpf
from identidade.models import PedidoRedefinicao, Pessoa
from permissao.models import Concessao


def _com(fabrica_pessoa, conceder_direto, cargo, escopo, nome='Pessoa'):
    pessoa = fabrica_pessoa(nome)
    conceder_direto(pessoa, cargo, escopo)
    return pessoa


def test_administrador_convida_pelo_painel_e_a_senha_temporaria_aparece(cenario, fabrica_pessoa, conceder_direto, entrar_no_painel, cpf_novo):
    cliente = entrar_no_painel(_com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x))
    corpo = {'nome': 'Convidada', 'email': 'c@exemplo.test', 'cpf': cpf_novo(), 'cargo': cenario.cargos_x['usuario'].pk, 'fazenda': cenario.f1.pk}
    resposta = cliente.post('/painel/identidade/pessoa/add/', corpo, follow=True)
    nova = Pessoa.objects.get(nome='Convidada')
    assert Concessao.objects.get(pessoa=nova).fazenda_id == cenario.f1.pk
    assert any('Senha temporária' in str(m) for m in get_messages(resposta.wsgi_request))


def test_convite_sem_escopo_ou_de_cargo_que_a_pessoa_nao_alcanca_nao_cria_ninguem(cenario, fabrica_pessoa, conceder_direto, entrar_no_painel, cpf_novo):
    curador = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['curador'], cenario.f1)
    cliente = entrar_no_painel(curador)
    total = Pessoa.objects.count()
    sem_escopo = {'nome': 'A', 'email': 'a@exemplo.test', 'cpf': cpf_novo(), 'cargo': cenario.cargos_x['usuario'].pk}
    assert cliente.post('/painel/identidade/pessoa/add/', sem_escopo).status_code == 200
    mesmo_nivel = {**sem_escopo, 'cpf': cpf_novo(), 'cargo': cenario.cargos_x['curador'].pk, 'fazenda': cenario.f1.pk}
    assert cliente.post('/painel/identidade/pessoa/add/', mesmo_nivel).status_code in (200, 403)
    outra_fazenda = {**sem_escopo, 'cpf': cpf_novo(), 'fazenda': cenario.f2.pk}
    assert cliente.post('/painel/identidade/pessoa/add/', outra_fazenda).status_code in (200, 403)
    assert Pessoa.objects.count() == total


def test_lista_de_pessoas_do_painel_nao_mostra_pessoa_de_outra_empresa(cenario, fabrica_pessoa, conceder_direto, entrar_no_painel):
    _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['usuario'], cenario.f1, 'Moradora de X')
    admin_y = _com(fabrica_pessoa, conceder_direto, cenario.cargos_y['administrador'], cenario.y, 'Admin de Y')
    pagina = entrar_no_painel(admin_y).get('/painel/identidade/pessoa/').content.decode()
    assert 'Admin de Y' in pagina
    assert 'Moradora de X' not in pagina
    assert admin_y.cpf_busca not in pagina


def test_acao_de_redefinir_senha_so_alcanca_quem_o_administrador_pode(cenario, fabrica_pessoa, conceder_direto, entrar_no_painel):
    admin_x = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x, 'Admin X')
    admin_y = _com(fabrica_pessoa, conceder_direto, cenario.cargos_y['administrador'], cenario.y, 'Admin Y')
    alvo = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['usuario'], cenario.f1, 'Alvo')
    pedido = {'action': 'redefinir_senha', '_selected_action': [alvo.pk]}
    entrar_no_painel(admin_y).post('/painel/identidade/pessoa/', pedido)
    assert not PedidoRedefinicao.objects.filter(pessoa=alvo).exists()
    entrar_no_painel(admin_x).post('/painel/identidade/pessoa/', pedido)
    assert PedidoRedefinicao.objects.filter(pessoa=alvo, solicitado_por=admin_x).count() == 1


def test_curador_com_ver_nao_tem_a_acao_de_redefinir(cenario, fabrica_pessoa, conceder_direto, entrar_no_painel):
    curador = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['curador'], cenario.f1, 'Curador')
    alvo = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['usuario'], cenario.f1, 'Alvo')
    entrar_no_painel(curador).post('/painel/identidade/pessoa/', {'action': 'redefinir_senha', '_selected_action': [alvo.pk]})
    assert not PedidoRedefinicao.objects.filter(pessoa=alvo).exists()


def test_pessoa_do_painel_tem_nome_legivel_e_nao_expoe_o_indice_do_cpf(cenario, fabrica_pessoa):
    pessoa = fabrica_pessoa('Ana Souza')
    assert (str(pessoa), pessoa.get_short_name()) == ('Ana Souza', 'Ana Souza')
    assert modulo_cpf.decifrar(pessoa.cpf_cifrado) not in str(pessoa)


def test_formulario_de_convite_so_oferece_o_que_a_pessoa_alcanca(cenario, fabrica_pessoa, conceder_direto, entrar_no_painel):
    cliente = entrar_no_painel(_com(fabrica_pessoa, conceder_direto, cenario.cargos_x['curador'], cenario.g1))
    pagina = cliente.get('/painel/identidade/pessoa/add/').content.decode()
    assert '>G1<' in pagina
    assert '>G2<' not in pagina
    assert '>FY<' not in pagina
    assert 'Empresa Y' not in pagina


def test_plataforma_redefine_a_senha_de_outro_administrador_da_plataforma(plataforma, fabrica_pessoa, entrar_no_painel):
    outra = fabrica_pessoa('Outra plataforma')
    outra.administrador_plataforma = True
    outra.save(update_fields=['administrador_plataforma'])
    entrar_no_painel(plataforma).post('/painel/identidade/pessoa/', {'action': 'redefinir_senha', '_selected_action': [outra.pk]})
    assert PedidoRedefinicao.objects.filter(pessoa=outra, solicitado_por=plataforma).count() == 1


def test_acao_de_redefinir_so_conta_o_pedido_criado(cenario, fabrica_pessoa, conceder_direto, entrar_no_painel):
    from django.contrib.messages import get_messages

    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x, 'Admin')
    alvo = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['usuario'], cenario.f1, 'Alvo')
    cliente = entrar_no_painel(admin)
    pedido = {'action': 'redefinir_senha', '_selected_action': [alvo.pk]}
    primeira = cliente.post('/painel/identidade/pessoa/', pedido, follow=True)
    segunda = cliente.post('/painel/identidade/pessoa/', pedido, follow=True)  # dentro do intervalo de 1 minuto
    assert any('1 de 1' in str(m) for m in get_messages(primeira.wsgi_request))
    assert any('0 de 1' in str(m) for m in get_messages(segunda.wsgi_request))
    assert PedidoRedefinicao.objects.filter(pessoa=alvo).count() == 1


def test_convite_de_cpf_que_ja_existe_pelo_painel_vira_pendente_sem_dado_da_pessoa(cenario, fabrica_pessoa, conceder_direto, entrar_no_painel):
    from django.contrib.messages import get_messages

    from permissao.models import Convite

    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    existente = fabrica_pessoa('Moradora de Y')
    total = Pessoa.objects.count()
    corpo = {'nome': 'Qualquer', 'email': 'q@exemplo.test', 'cpf': modulo_cpf.decifrar(existente.cpf_cifrado), 'cargo': cenario.cargos_x['usuario'].pk, 'fazenda': cenario.f1.pk}
    resposta = entrar_no_painel(admin).post('/painel/identidade/pessoa/add/', corpo, follow=True)
    assert resposta.status_code == 200
    assert any('Convite enviado' in str(m) for m in get_messages(resposta.wsgi_request))
    assert 'Moradora de Y' not in resposta.content.decode()
    assert Pessoa.objects.count() == total
    assert Convite.objects.filter(pessoa=existente).count() == 1
    assert not Concessao.objects.filter(pessoa=existente, empresa=cenario.x).exists()
