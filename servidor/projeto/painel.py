"""Painel de administração (R17; T5.2): o Django admin atrás das mesmas regras da API.

Entra só quem tem alguma ação de gestão em algum escopo, com a sessão vigente do R15 (ociosidade e teto de 12 h) e a
senha já trocada. Toda tela roda dentro de `com_permissao` e é renderizada ali dentro: a resposta preguiçosa do
Django seria montada depois de a transação fechar, já sem o contexto assinado da RLS. A troca de senha do admin fica
fechada: só `identidade.senha.trocar_senha` (via API) revoga sessões e acessos (R15).
"""

from functools import wraps

from django import forms
from django.contrib import messages
from django.contrib.admin import AdminSite, ModelAdmin
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.http import HttpResponseRedirect

from identidade import sessao
from permissao.pode import age_em_algum_escopo, com_permissao, escopos_da_acao

# O que abre o painel: ver o território, sozinho, não basta (Técnico e Usuário veem e não administram).
ACOES_DE_GESTAO = (
    'criar_empresa', 'criar_fazenda', 'criar_sub_area', 'convidar_pessoa', 'revogar_acesso', 'redefinir_senha',
    'gerenciar_cargo',
)
ACOES_DO_PAINEL = ('ver', *ACOES_DE_GESTAO)


class FormularioEntrada(AuthenticationForm):
    username = forms.CharField(label='CPF', max_length=64)
    error_messages = {**AuthenticationForm.error_messages, 'invalid_login': 'CPF ou senha incorretos.'}

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if getattr(user, 'deve_trocar_senha', False):
            # A troca obrigatória é da API (`trocar-senha`); o painel não deixa entrar com senha temporária.
            raise forms.ValidationError('Troque a senha temporária pelo aplicativo antes de usar o painel.', code='troca')


class PainelSite(AdminSite):
    site_header = 'phati'
    site_title = 'phati'
    index_title = 'Administração'
    login_form = FormularioEntrada

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.disable_action('delete_selected')

    def has_permission(self, request):
        pessoa = request.user
        return bool(
            pessoa.is_authenticated
            and sessao.sessao_vigente(request)
            and not getattr(pessoa, 'deve_trocar_senha', True)
            and age_em_algum_escopo(pessoa, *ACOES_DE_GESTAO)
        )

    def admin_view(self, view, cacheable=False):
        protegida = super().admin_view(view, cacheable)

        @wraps(protegida)
        def interna(request, *args, **kwargs):
            with com_permissao(request.user, *ACOES_DO_PAINEL):
                resposta = protegida(request, *args, **kwargs)
                if callable(getattr(resposta, 'render', None)):
                    resposta.render()
                return resposta

        return interna

    def login(self, request, extra_context=None):
        resposta = super().login(request, extra_context)
        if request.method == 'POST' and request.user.is_authenticated:
            sessao.carimbar(request)  # o `login()` do Django não grava `entrada_em` nem `ultima_atividade`
        return resposta

    def password_change(self, request, extra_context=None):
        raise PermissionDenied


def escolher_escopo(empresa, fazenda, sub_area):
    """O escopo da concessão ou do convite é o objeto mais específico escolhido; nenhum, erro de formulário."""
    escolhido = sub_area or fazenda or empresa
    if escolhido is None:
        raise forms.ValidationError('Escolha a empresa, a fazenda ou a sub-área.', code='escopo_ausente')
    return escolhido


def do_escopo(consulta, pessoa, acao, *, empresa=None, fazenda=None, sub_area=None, irmas=False):
    """Restringe `consulta` ao que `pessoa` alcança com `acao`. O painel não confia só na RLS: este filtro vale
    também quando o ORM roda como dono (testes) e dá a granularidade de fazenda e sub-área que a RLS não tem."""
    escopos = escopos_da_acao(pessoa, acao)
    if escopos.plataforma:
        return consulta
    filtro = Q(pk__in=[])
    if empresa:
        filtro |= Q(**{f'{empresa}__in': escopos.empresas})
        if irmas:  # quem age numa fazenda enxerga a empresa dela (e os cargos), não os dados das outras fazendas
            filtro |= Q(**{f'{empresa}__in': escopos.empresas_das_fazendas})
    if fazenda:
        filtro |= Q(**{f'{fazenda}__in': escopos.fazendas | escopos.fazendas_das_sub_areas})
    if sub_area:
        filtro |= Q(**{f'{sub_area}__in': escopos.sub_areas})
    return consulta.filter(filtro)


class AdministracaoPorServico(ModelAdmin):
    """Toda gravação passa por um serviço de domínio (`pode()`, trava, auditoria): o admin só monta o formulário.

    Nenhuma tela edita linha direto: `has_change_permission` é falso salvo onde a subclasse o abre, e a ação em
    massa de apagar não existe (`PainelSite.__init__` a desliga; apagaria sem passar pelo serviço). O `LogEntry` do
    Django grava só o resumo da tela; o registro de auditoria é o `auditar()` do serviço.
    """

    acao_de_leitura = 'ver'
    acao_de_criacao = None
    acao_de_remocao = None
    acao_de_alteracao = None

    def _age(self, request, acao):
        return acao is not None and age_em_algum_escopo(request.user, acao)

    def has_module_permission(self, request):
        return self._age(request, self.acao_de_leitura)

    def has_view_permission(self, request, obj=None):
        return self._age(request, self.acao_de_leitura)

    def has_add_permission(self, request):
        return self._age(request, self.acao_de_criacao)

    def has_change_permission(self, request, obj=None):
        return self._age(request, self.acao_de_alteracao)

    def has_delete_permission(self, request, obj=None):
        return self._age(request, self.acao_de_remocao)

    def _recusar_com_mensagem(self, request, chamar):
        try:
            return chamar()
        except ValidationError as erro:
            messages.error(request, ' '.join(erro.messages))
            return HttpResponseRedirect(request.get_full_path())

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        return self._recusar_com_mensagem(
            request, lambda: super(AdministracaoPorServico, self).changeform_view(request, object_id, form_url, extra_context)
        )

    def delete_view(self, request, object_id, extra_context=None):
        return self._recusar_com_mensagem(
            request, lambda: super(AdministracaoPorServico, self).delete_view(request, object_id, extra_context)
        )

    def concluir_criacao(self, obj, criado):
        """Depois de o serviço gravar, o `obj` do formulário (nunca salvo) passa a apontar para a linha criada."""
        obj.pk = criado.pk
        obj._state.adding = False
