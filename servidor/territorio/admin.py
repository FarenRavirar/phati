"""Painel territorial (T5.2): empresa, fazenda e sub-área, criadas pelos serviços de `cadastro`."""

from django import forms
from django.contrib import admin, messages

from projeto.painel import EMPRESAS, SUB_AREAS, AdministracaoPorServico, do_escopo
from territorio import cadastro
from territorio.models import Empresa, Fazenda, SubArea


class FormularioEmpresa(forms.ModelForm):
    nome_administrador = forms.CharField(max_length=200)
    email_administrador = forms.EmailField(max_length=254)
    cpf_administrador = forms.CharField(max_length=20)

    class Meta:
        model = Empresa
        fields = ('nome',)


@admin.register(Empresa)
class EmpresaAdmin(AdministracaoPorServico):
    form = FormularioEmpresa
    list_display = ('nome', 'criada_em')
    acao_de_criacao = 'criar_empresa'

    def get_queryset(self, request):
        return do_escopo(super().get_queryset(request), request.user, 'ver', empresa='pk', irmas=True)

    def save_model(self, request, obj, form, change):
        dados = form.cleaned_data
        empresa, administrador, temporaria = cadastro.criar_empresa(
            request.user, dados['nome'], dados['nome_administrador'], dados['email_administrador'], dados['cpf_administrador']
        )
        self.concluir_criacao(obj, empresa)
        messages.warning(request, f'Senha temporária de {administrador.nome} (mostrada uma vez): {temporaria}')


class FormularioFazenda(forms.ModelForm):
    class Meta:
        model = Fazenda
        fields = ('empresa', 'nome')


@admin.register(Fazenda)
class FazendaAdmin(AdministracaoPorServico):
    form = FormularioFazenda
    list_display = ('nome', 'empresa')
    acao_de_criacao = 'criar_fazenda'
    campos_do_escopo = {'empresa': ('criar_fazenda', EMPRESAS)}

    def get_queryset(self, request):
        return do_escopo(super().get_queryset(request), request.user, 'ver', empresa='empresa_id', fazenda='pk', ancestral='pk')

    def save_model(self, request, obj, form, change):
        self.concluir_criacao(obj, cadastro.criar_fazenda(request.user, form.cleaned_data['empresa'], form.cleaned_data['nome']))


class FormularioSubArea(forms.ModelForm):
    class Meta:
        model = SubArea
        fields = ('fazenda', 'pai', 'nome')


@admin.register(SubArea)
class SubAreaAdmin(AdministracaoPorServico):
    form = FormularioSubArea
    list_display = ('nome', 'fazenda', 'nivel')
    acao_de_criacao = 'criar_sub_area'
    campos_do_escopo = {
        'fazenda': ('criar_sub_area', {'empresa': 'empresa_id', 'fazenda': 'pk', 'ancestral': 'pk'}),
        'pai': ('criar_sub_area', SUB_AREAS),
    }

    def get_queryset(self, request):
        return do_escopo(
            super().get_queryset(request), request.user, 'ver',
            empresa='empresa_id', fazenda='fazenda_id', sub_area='pk', caminho='caminho',
        )

    def save_model(self, request, obj, form, change):
        dados = form.cleaned_data
        self.concluir_criacao(obj, cadastro.criar_sub_area(request.user, dados['fazenda'], dados['nome'], dados['pai']))
