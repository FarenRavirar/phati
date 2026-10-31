"""Painel de pessoas (T5.2): convite com senha temporária e redefinição de senha, sempre pelos serviços."""

from django import forms
from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.urls import reverse

from identidade import cpf as modulo_cpf
from identidade import redefinicao
from identidade.models import PedidoRedefinicao, Pessoa
from permissao import convite
from permissao.api import pessoas_do_escopo
from permissao.models import Cargo
from permissao.pode import pode
from projeto.painel import ACOES_DE_PESSOAS, EMPRESAS, FAZENDAS, SUB_AREAS, AdministracaoPorServico, escolher_escopo
from territorio.models import Empresa, Fazenda, SubArea


class FormularioConvite(forms.ModelForm):
    cpf = forms.CharField(max_length=20)
    cargo = forms.ModelChoiceField(Cargo.objects.all())
    empresa = forms.ModelChoiceField(Empresa.objects.all(), required=False, help_text='Vale o mais específico dos três.')
    fazenda = forms.ModelChoiceField(Fazenda.objects.all(), required=False)
    sub_area = forms.ModelChoiceField(SubArea.objects.all(), required=False)

    class Meta:
        model = Pessoa
        fields = ('nome', 'email')

    def clean(self):
        dados = super().clean() or {}
        if not self.errors:
            dados['escopo'] = escolher_escopo(dados.get('empresa'), dados.get('fazenda'), dados.get('sub_area'))
        return dados


@admin.register(Pessoa)
class PessoaAdmin(AdministracaoPorServico):
    form = FormularioConvite
    list_display = ('nome', 'email', 'empresa_origem')
    list_select_related = ('empresa_origem',)
    search_fields = ('nome', 'email')
    actions = ['redefinir_senha']
    acao_de_leitura = ACOES_DE_PESSOAS
    acao_de_criacao = 'convidar_pessoa'
    campos_do_escopo = {
        'cargo': ('convidar_pessoa', {'empresa': 'empresa_id', 'irmas': True}),
        'empresa': ('convidar_pessoa', EMPRESAS),
        'fazenda': ('convidar_pessoa', FAZENDAS),
        'sub_area': ('convidar_pessoa', SUB_AREAS),
    }

    def get_queryset(self, request):
        return pessoas_do_escopo(request.user, ACOES_DE_PESSOAS)

    def save_model(self, request, obj, form, change):
        dados = form.cleaned_data
        pessoa, temporaria = convite.convidar_por_cpf(
            request.user, dados['nome'], dados['email'], dados['cpf'], dados['cargo'], dados['escopo']
        )
        if pessoa is None:  # CPF que já existe: convite pendente, sem dado da pessoa na tela (R24)
            messages.info(request, 'Convite enviado.')
            return
        self.concluir_criacao(obj, pessoa)
        messages.warning(request, f'Senha temporária de {pessoa.nome} (mostrada uma vez): {temporaria}')

    def response_add(self, request, obj, post_url_continue=None):
        if obj.pk is None:  # convite pendente: não há linha de pessoa para abrir
            return HttpResponseRedirect(reverse('admin:identidade_pessoa_changelist'))
        return super().response_add(request, obj, post_url_continue)

    @admin.action(description='Enviar link de redefinição de senha', permissions=['redefinir'])
    def redefinir_senha(self, request, queryset):
        enviados = 0
        for alvo in queryset:
            empresa = redefinicao.empresa_de_atuacao(alvo, request.user)
            # Mesma regra da rota: `redefinir_senha` na empresa e, por último, `pode_iniciar_redefinicao` (R5).
            # Sem empresa (conta da plataforma), `pode()` sem alvo só passa a plataforma.
            if pode(request.user, 'redefinir_senha', empresa) and redefinicao.pode_iniciar_redefinicao(request.user, alvo):
                antes = PedidoRedefinicao.objects.filter(pessoa=alvo).count()
                redefinicao.pedir_redefinicao(modulo_cpf.decifrar(alvo.cpf_cifrado), solicitante=request.user)
                # O serviço devolve sempre `None` (resposta neutra); pedido em intervalo ou no teto não cria linha.
                enviados += PedidoRedefinicao.objects.filter(pessoa=alvo).count() > antes
        messages.info(request, f'{enviados} de {queryset.count()} pedido(s) de redefinição aceito(s).')

    def has_redefinir_permission(self, request):
        return self._age(request, 'redefinir_senha')
