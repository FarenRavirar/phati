"""Rotas de identidade da API: entrar, sair, trocar senha, redefinir senha e renovar o acesso do aplicativo (R2 a R6, R15)."""

from django.contrib.auth import logout
from ninja import Field, Router, Schema

from identidade import acesso, redefinicao, senha, sessao

roteador = Router(tags=['identidade'])


class EntradaEntrar(Schema):
    cpf: str
    senha: str
    dispositivo: str | None = Field(None, max_length=200)  # com dispositivo, o aplicativo recebe um segredo; sem, o navegador recebe o cookie


class SaidaEntrar(Schema):
    deve_trocar_senha: bool
    segredo: str | None = None


class EntradaTrocarSenha(Schema):
    senha_atual: str
    senha_nova: str


class EntradaSolicitarRedefinicao(Schema):
    cpf: str


class EntradaConfirmarRedefinicao(Schema):
    segredo: str
    senha_nova: str


class EntradaRenovar(Schema):
    segredo: str


class SaidaRenovar(Schema):
    segredo: str


class SaidaErro(Schema):
    detalhe: str


@roteador.post('entrar', auth=None, url_name='entrar', response={200: SaidaEntrar, 401: SaidaErro})
def entrar(request, dados: EntradaEntrar):
    # CPF inexistente, senha errada, conta bloqueada e senha temporária vencida: o mesmo 401 (A2).
    entrada = acesso.entrar(request, dados.cpf, dados.senha, dados.dispositivo)
    if entrada is None:
        return 401, {'detalhe': 'credenciais_invalidas'}
    pessoa, segredo = entrada
    return 200, {'deve_trocar_senha': pessoa.deve_trocar_senha, 'segredo': segredo}


@roteador.post('sair', url_name='sair', response={204: None})
def sair(request):
    # Encerra o que vier na requisição: a autenticação aceita cookie ou Bearer e o cookie ganha quando os dois vêm
    # (achado do Qodo, PR #14).
    # Mesma leitura do HttpBearer do ninja: esquema em qualquer caixa, separado por um espaço (achado do Codex, PR #14).
    esquema, _, segredo = request.headers.get('Authorization', '').partition(' ')
    if esquema.lower() == 'bearer' and segredo:
        sessao.revogar_acesso(segredo.strip())
    logout(request)
    return 204, None


@roteador.post('trocar-senha', url_name='trocar_senha', response={204: None})
def trocar_senha(request, dados: EntradaTrocarSenha):
    # Troca revoga toda sessão e todo acesso da pessoa (R15): depois dela, o cliente entra de novo.
    senha.trocar_senha(request.user, dados.senha_atual, dados.senha_nova)
    return 204, None


@roteador.post('redefinir-senha/solicitar', auth=None, url_name='redefinir_senha_solicitar', response={204: None})
def solicitar_redefinicao(request, dados: EntradaSolicitarRedefinicao):
    redefinicao.pedir_redefinicao(dados.cpf)  # resposta neutra: CPF inexistente e existente são indistinguíveis (R5)
    return 204, None


@roteador.post('redefinir-senha/confirmar', auth=None, url_name='redefinir_senha_confirmar', response={204: None})
def confirmar_redefinicao(request, dados: EntradaConfirmarRedefinicao):
    redefinicao.confirmar_redefinicao(dados.segredo, dados.senha_nova)
    return 204, None


@roteador.post('acesso/renovar', auth=None, url_name='acesso_renovar', response={200: SaidaRenovar, 401: SaidaErro})
def renovar_acesso(request, dados: EntradaRenovar):
    renovado = sessao.renovar_acesso(dados.segredo)
    if renovado is None:
        return 401, {'detalhe': 'acesso_invalido'}
    return 200, {'segredo': renovado[1]}
