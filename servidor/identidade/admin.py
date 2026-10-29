"""Painel de pessoas (T5.2): convite com senha temporária e redefinição de senha, sempre pelos serviços."""

from django import forms
from django.contrib import admin, messages

from identidade import cpf as modulo_cpf
from identidade import redefinicao
from identidade.models import Pessoa
from permissao import delegacao
from permissao.api import pessoas_do_escopo
from permissao.models import Cargo
from permissao.pode import pode
from projeto.painel import AdministracaoPorServico, escolher_escopo
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
    search_fields = ('nome', 'email')
    actions = ['redefinir_senha']
    acao_de_leitura = 'convidar_pessoa'
    acao_de_criacao = 'convidar_pessoa'

    def get_queryset(self, request):
        return pessoas_do_escopo(request.user)

    def save_model(self, request, obj, form, change):
        dados = form.cleaned_data
        pessoa, temporaria = delegacao.convidar(
            request.user, dados['nome'], dados['email'], dados['cpf'], dados['cargo'], dados['escopo']
        )
        self.concluir_criacao(obj, pessoa)
        messages.warning(request, f'Senha temporária de {pessoa.nome} (mostrada uma vez): {temporaria}')

    @admin.action(description='Enviar link de redefinição de senha', permissions=['redefinir'])
    def redefinir_senha(self, request, queryset):
        enviados = 0
        for alvo in queryset:
            empresa = redefinicao.empresa_de_atuacao(alvo)
            # Mesma regra da rota: `redefinir_senha` na empresa e, por último, `pode_iniciar_redefinicao` (R5).
            if empresa and pode(request.user, 'redefinir_senha', empresa) and redefinicao.pode_iniciar_redefinicao(request.user, alvo):
                redefinicao.pedir_redefinicao(modulo_cpf.decifrar(alvo.cpf_cifrado), solicitante=request.user)
                enviados += 1
        messages.info(request, f'{enviados} de {queryset.count()} pedido(s) de redefinição aceito(s).')

    def has_redefinir_permission(self, request):
        return self._age(request, 'redefinir_senha')
