"""Painel de acesso (T5.2): concessão, revogação e cargo, sempre pelos serviços de `delegacao` e `cargo`."""

from django import forms
from django.contrib import admin

from permissao import delegacao
from permissao.cargo import gerenciar_cargo
from permissao.models import Cargo, Concessao, Permissao
from projeto.painel import AdministracaoPorServico, do_escopo, escolher_escopo


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
    acao_de_leitura = 'convidar_pessoa'
    acao_de_criacao = 'convidar_pessoa'
    acao_de_remocao = 'revogar_acesso'  # apagar aqui é revogar: a linha fica, com `revogada_em` e `revogada_por`

    def get_queryset(self, request):
        return do_escopo(
            super().get_queryset(request), request.user, 'convidar_pessoa',
            empresa='empresa_id', fazenda='fazenda_id', sub_area='sub_area_id',
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

    class Meta:
        model = Cargo
        fields = ('nome', 'empresa', 'base')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields['codigos'].initial = list(self.instance.permissoes.values_list('pk', flat=True))


@admin.register(Cargo)
class CargoAdmin(AdministracaoPorServico):
    form = FormularioCargo
    list_display = ('nome', 'empresa', 'base')
    acao_de_leitura = 'convidar_pessoa'
    acao_de_criacao = 'gerenciar_cargo'
    acao_de_alteracao = 'gerenciar_cargo'

    def get_queryset(self, request):
        return do_escopo(super().get_queryset(request), request.user, 'convidar_pessoa', empresa='empresa_id', irmas=True)

    def get_readonly_fields(self, request, obj=None):
        return ('empresa', 'base') if obj else ()  # não mudam depois de criados (gatilho da migração 0002)

    def save_model(self, request, obj, form, change):
        dados = form.cleaned_data
        codigos = [permissao.pk for permissao in dados['codigos']]
        if change:
            gerenciar_cargo(request.user, obj.empresa, dados['nome'], codigos, cargo=obj)
        else:
            self.concluir_criacao(obj, gerenciar_cargo(request.user, dados['empresa'], dados['nome'], codigos, base=dados['base']))
