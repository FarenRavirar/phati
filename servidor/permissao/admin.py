"""Painel de acesso (T5.2): concessão, revogação e cargo, sempre pelos serviços de `delegacao` e `cargo`."""

from django import forms
from django.contrib import admin

from permissao import delegacao
from permissao.api import pessoas_do_escopo
from permissao.cargo import gerenciar_cargo
from permissao.models import Cargo, Concessao, Permissao
from projeto.painel import ACOES_DE_PESSOAS, EMPRESAS, FAZENDAS, SUB_AREAS, AdministracaoPorServico, do_escopo, escolher_escopo


class FormularioConcessao(forms.ModelForm):
    class Meta:
        model = Concessao
        fields = ('pessoa', 'cargo', 'empresa', 'fazenda', 'sub_area', 'inicio', 'fim')
        help_texts = {'empresa': 'Vale o mais específico dos três.'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in ('empresa', 'fazenda', 'sub_area'):
            self.fields[campo].required = False

    def clean(self):
        dados = super().clean() or {}
        if not self.errors:
            dados['escopo'] = escolher_escopo(dados.get('empresa'), dados.get('fazenda'), dados.get('sub_area'))
        return dados


@admin.register(Concessao)
class ConcessaoAdmin(AdministracaoPorServico):
    form = FormularioConcessao
    list_display = ('pessoa', 'cargo', 'empresa', 'fazenda', 'sub_area', 'inicio', 'fim', 'revogada_em')
    autocomplete_fields = ('pessoa',)
    acao_de_leitura = ACOES_DE_PESSOAS
    acao_de_criacao = 'convidar_pessoa'
    acao_de_remocao = 'revogar_acesso'  # apagar aqui é revogar: a linha fica, com `revogada_em` e `revogada_por`
    campos_do_escopo = {
        'cargo': ('convidar_pessoa', {'empresa': 'empresa_id', 'irmas': True}),
        'empresa': ('convidar_pessoa', EMPRESAS),
        'fazenda': ('convidar_pessoa', FAZENDAS),
        'sub_area': ('convidar_pessoa', SUB_AREAS),
    }

    def restringir_campos(self, request, campos):
        super().restringir_campos(request, campos)
        if 'pessoa' in campos:  # a tabela `pessoa` não tem RLS: sem isto qualquer id postado seria aceito
            campos['pessoa'].queryset = pessoas_do_escopo(request.user, ACOES_DE_PESSOAS)

    def get_queryset(self, request):
        return do_escopo(
            super().get_queryset(request), request.user, ACOES_DE_PESSOAS,
            empresa='empresa_id', fazenda='fazenda_id', sub_area='sub_area_id', caminho='sub_area__caminho',
        )

    def save_model(self, request, obj, form, change):
        dados = form.cleaned_data
        concessao = delegacao.conceder(
            request.user, dados['pessoa'], dados['cargo'], dados['escopo'], (), dados['inicio'], dados['fim']
        )
        self.concluir_criacao(obj, concessao)

    def delete_model(self, request, obj):
        delegacao.revogar_concessao(request.user, obj)

    def delete_queryset(self, request, queryset):
        for concessao in queryset:
            delegacao.revogar_concessao(request.user, concessao)


class FormularioCargo(forms.ModelForm):
    codigos = forms.ModelMultipleChoiceField(
        Permissao.objects.all(), required=False, widget=forms.CheckboxSelectMultiple, label='Permissões'
    )
    # A versão que quem edita leu volta no envio; o serviço recusa se o cargo mudou nesse meio tempo.
    versao = forms.IntegerField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = Cargo
        fields = ('nome', 'empresa', 'base')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields['codigos'].initial = list(self.instance.permissoes.values_list('pk', flat=True))
            self.fields['versao'].initial = self.instance.versao


@admin.register(Cargo)
class CargoAdmin(AdministracaoPorServico):
    form = FormularioCargo
    list_display = ('nome', 'empresa', 'base')
    acao_de_leitura = ('convidar_pessoa', 'gerenciar_cargo')  # quem só gerencia cargo também precisa abri-lo
    acao_de_criacao = 'gerenciar_cargo'
    acao_de_alteracao = 'gerenciar_cargo'
    campos_do_escopo = {'empresa': ('gerenciar_cargo', EMPRESAS)}

    def get_queryset(self, request):
        return do_escopo(
            super().get_queryset(request), request.user, ('convidar_pessoa', 'gerenciar_cargo'), empresa='empresa_id', irmas=True
        )

    def get_readonly_fields(self, request, obj=None):
        return ('empresa', 'base') if obj else ()  # não mudam depois de criados (gatilho da migração 0002)

    def save_model(self, request, obj, form, change):
        dados = form.cleaned_data
        codigos = [permissao.pk for permissao in dados['codigos']]
        if change:
            gerenciar_cargo(request.user, obj.empresa, dados['nome'], codigos, cargo=obj, versao=dados['versao'])
        else:
            self.concluir_criacao(obj, gerenciar_cargo(request.user, dados['empresa'], dados['nome'], codigos, base=dados['base']))
