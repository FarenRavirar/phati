"""Convite de CPF que já existe (R24; plan.md §Convite de pessoa que já existe).

CPF sem cadastro segue `delegacao.convidar` (cria a pessoa, concede, envia a senha temporária). CPF já cadastrado não
ganha concessão: grava um convite pendente, e a concessão nasce no aceite da pessoa, que refaz as regras de R10 com
quem convidou. Quem convida não recebe dado de quem já existe. O e-mail de aviso não sai daqui: R6 limita o e-mail a
credenciais, e ampliar essa regra é decisão do mantenedor (T5.5i).
"""

from datetime import timedelta

from django.contrib.auth.hashers import check_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from comum.auditoria import auditar
from comum.models import EventoAuditoria
from identidade import cpf as modulo_cpf
from identidade import email
from identidade.login import _HASH_FALSO
from identidade.models import Pessoa
from permissao import delegacao
from permissao.delegacao import _gravar, _proposta, _travar_pessoa, exigir_categoria_compativel, pode_conceder
from permissao.models import Cargo, Convite, ConviteCategoria
from permissao.pode import com_permissao, escopo_de, filtro_do_escopo, unir_escopos
from territorio.models import Empresa

# Confirmada pelo mantenedor (D053): 7 dias; o MateCat usa 3.
VALIDADE = timedelta(days=7)
# Limites contra encher a caixa de alguém ou usar o sistema para enviar e-mail em massa (AGENTS.md, prática 9).
# Referências de mercado (pesquisa de 2026-10-29): Supabase deixa 60 s entre reenvios por usuário; Discourse limita
# reenvio de convite a 10 por hora; Clerk limita convites a 100 por hora; o MateCat limita 50 e-mails por pedido.
INTERVALO_ENTRE_ENVIOS = timedelta(seconds=60)
MAXIMO_DE_ENVIOS_POR_CONVITE = 4  # o primeiro e três reenvios
MAXIMO_DE_CONVITES_POR_HORA = 50  # por quem convida; conta convite de CPF existente e pessoa nova criada pelo convite
RETENCAO_DE_VENCIDOS = timedelta(days=30)  # convite vencido sem resposta continua na lista de quem convidou por este tempo
_TRAVA_DA_COTA = 5301  # primeiro número do par da trava consultiva (o segundo é o id de quem convida)


def _exigir_em_aberto(convite):
    """Convite aceito, recusado ou cancelado não muda mais (um lugar só para as três respostas e o reenvio)."""
    if convite.aceito_em or convite.recusado_em or convite.cancelado_em:
        raise ValidationError('Convite já respondido.', code='convite_encerrado')


def _com_fim_no_futuro():
    # Convite cujo `fim` já passou nunca será aceito (o banco recusa `fim <= inicio`): fora das duas listas (Sourcery).
    return Q(fim__isnull=True) | Q(fim__gt=timezone.now())


def _pendentes(pessoa):
    return Convite.objects.filter(
        _com_fim_no_futuro(), pessoa=pessoa, aceito_em__isnull=True, recusado_em__isnull=True,
        cancelado_em__isnull=True, expira_em__gt=timezone.now(),
    )


def _avisar(convite, pessoa):
    email.enviar_aviso_de_convite(pessoa, convite.empresa_nome, convite.cargo_nome, convite.expira_em)


def _exigir_pode_enviar(convite):
    """Teto de e-mails por convite e intervalo entre envios: vale para reenviar e para substituir o convite."""
    if convite.envios >= MAXIMO_DE_ENVIOS_POR_CONVITE:
        raise ValidationError('Limite de reenvios do convite.', code='reenvio_esgotado')
    if timezone.now() - convite.enviado_em < INTERVALO_ENTRE_ENVIOS:
        raise ValidationError('Aguarde antes de reenviar.', code='reenvio_cedo')


def _exigir_cota(quem):
    """Trava e confere a cota por hora de quem convida, para os dois caminhos (CPF novo e existente). A trava
    consultiva é por remetente: pedidos para pessoas diferentes não disputam a trava da pessoa, e sem ela dois
    pedidos leriam 49 e gravariam o 50º e o 51º (Greptile e Codex, PR #16). Sem deadlock: ela vem antes de toda
    trava de linha deste fluxo."""
    with connection.cursor() as consulta:
        consulta.execute('SELECT pg_advisory_xact_lock(%s, %s)', [_TRAVA_DA_COTA, quem.pk])
    desde = timezone.now() - timedelta(hours=1)
    convites = Convite.objects.filter(convidado_por=quem, criado_em__gt=desde).count()
    criadas = EventoAuditoria.objects.filter(acao='pessoa_criada', pessoa_id=quem.pk, hora_servidor__gt=desde).count()
    if convites + criadas >= MAXIMO_DE_CONVITES_POR_HORA:
        raise ValidationError('Convites demais na última hora.', code='convites_demais')


def _registrar(quem, pessoa, proposta, categorias, inicio):
    with transaction.atomic():
        _travar_pessoa(pessoa.pk)
        envios_anteriores = 0
        for igual in _pendentes(pessoa).filter(
            convidado_por=quem, cargo_id=proposta.cargo_id, empresa_id=proposta.empresa_id,
            fazenda_id=proposta.fazenda_id, sub_area_id=proposta.sub_area_id,
        ):
            ids_antigos = set(igual.categorias.values_list('pk', flat=True))
            if (igual.inicio, igual.fim, ids_antigos) == (inicio, proposta.fim, {c.pk for c in categorias}):
                return  # o mesmo convite repetido não empilha linhas nem renova a validade
            # Mesmo lugar e cargo com outro período ou outras categorias: o novo vale e o antigo sai, senão o aceite
            # criaria o acesso antigo (Greptile, PR #16). Substituir manda outro e-mail, então herda o intervalo e o
            # teto de envios do reenvio: sem isso 50 substituições seguidas encheriam a caixa da pessoa.
            _exigir_pode_enviar(igual)
            envios_anteriores = igual.envios
            igual.cancelado_em = timezone.now()
            igual.save(update_fields=['cancelado_em'])
            auditar('convite_cancelado', quem, igual, igual.empresa_id, {'substituido': True})
        convite = Convite.objects.create(
            pessoa=pessoa, convidado_por=quem, cargo=proposta.cargo, empresa_id=proposta.empresa_id,
            fazenda_id=proposta.fazenda_id, sub_area_id=proposta.sub_area_id, inicio=inicio, fim=proposta.fim,
            empresa_nome=Empresa.objects.get(pk=proposta.empresa_id).nome, cargo_nome=proposta.cargo.nome,
            expira_em=timezone.now() + VALIDADE, envios=envios_anteriores + 1,
        )
        ConviteCategoria.objects.bulk_create(ConviteCategoria(convite=convite, categoria=c) for c in categorias)
        auditar('convite_criado', quem, convite, proposta.empresa_id, {'pessoa_id': pessoa.pk, 'cargo_id': proposta.cargo_id})
        _avisar(convite, pessoa)


def convidar_por_cpf(quem, nome, email, cpf_texto, cargo, escopo, categorias=(), inicio=None, fim=None):
    """Convida pelo CPF. Devolve `(pessoa, senha_temporaria)` se o CPF era novo e `(None, None)` se já existia.

    A autoridade de quem convida é conferida antes de olhar o CPF, para os dois casos negarem igual. CPF inválido
    levanta `ValidationError`; negado, `PermissionDenied`.
    """
    if quem is None or not quem.is_authenticated:
        raise PermissionDenied  # antes de `_proposta`, que exige uma Pessoa em `concedida_por`
    categorias = tuple(categorias)
    exigir_categoria_compativel(cargo, categorias)
    proposta = _proposta(quem, cargo, escopo, inicio, fim)
    if not pode_conceder(quem, proposta, categorias):
        raise PermissionDenied
    busca = modulo_cpf.chave_de_busca(modulo_cpf.normalizar_cpf(cpf_texto))
    with transaction.atomic():
        _exigir_cota(quem)
        existente = Pessoa.objects.filter(cpf_busca=busca).first()
        if existente is None:
            try:
                return delegacao.convidar(quem, nome, email, cpf_texto, cargo, escopo, categorias, inicio, fim)
            except ValidationError as erro:
                if erro.code != 'cpf_duplicado':
                    raise
                existente = Pessoa.objects.get(cpf_busca=busca)  # outro convite criou a pessoa entre a consulta e a gravação
        # CPF novo paga o Argon2 da senha temporária; o existente paga um equivalente, senão o tempo mostra o cadastro (T5.5c).
        check_password('sem efeito', _HASH_FALSO)
        _registrar(quem, existente, proposta, categorias, inicio)
    return None, None


def convites_da_pessoa(pessoa):
    return list(_pendentes(pessoa).order_by('pk'))


def _convite_aberto(pessoa, convite_id):
    """O convite é da pessoa, ainda não foi aceito nem recusado e não venceu; outra coisa é 404 ou erro de regra."""
    convite = Convite.objects.select_for_update().get(pk=convite_id, pessoa=pessoa)
    _exigir_em_aberto(convite)
    agora = timezone.now()
    if convite.expira_em <= agora or (convite.fim is not None and convite.fim <= agora):
        raise ValidationError('Convite vencido.', code='convite_vencido')
    return convite


def aceitar(pessoa, convite_id):
    """Cria a concessão proposta, refazendo as regras de R10 com quem convidou. Devolve a concessão."""
    with transaction.atomic():
        _travar_pessoa(pessoa.pk)
        convite = _convite_aberto(pessoa, convite_id)
        convidador = Pessoa.objects.get(pk=convite.convidado_por_id)
        # A pessoa que aceita não tem escopo na empresa: a gravação e as checagens rodam com o contexto de quem convidou.
        with com_permissao(convidador, 'convidar_pessoa'):
            proposta = _proposta(
                convidador, Cargo.objects.get(pk=convite.cargo_id), escopo_de(convite), convite.inicio, convite.fim
            )
            categorias = tuple(convite.categorias.all())
            if not pode_conceder(convidador, proposta, categorias):
                raise ValidationError('Quem convidou não pode mais conceder isto.', code='convite_sem_autoridade')
            concessao = _gravar(convidador, proposta, pessoa, categorias)
        convite.aceito_em = timezone.now()
        convite.save(update_fields=['aceito_em'])
        auditar('convite_aceito', pessoa, convite, convite.empresa_id, {'concessao_id': concessao.pk})
    return concessao


def recusar(pessoa, convite_id):
    with transaction.atomic():
        _travar_pessoa(pessoa.pk)
        convite = Convite.objects.select_for_update().get(pk=convite_id, pessoa=pessoa)
        _exigir_em_aberto(convite)
        convite.recusado_em = timezone.now()
        convite.save(update_fields=['recusado_em'])
        auditar('convite_recusado', pessoa, convite, convite.empresa_id)



def convites_enviados(quem):
    """Convites sem resposta de `quem`, vencidos recentes inclusive, só dos lugares onde ele ainda convida: quem perdeu
    o acesso a uma empresa não vê mais o nome dela nem o cargo que ofereceu (Sourcery, PR #16). Não carrega a pessoa: quem convida não vê dado de quem já existe (R24)."""
    escopos = unir_escopos(quem, 'convidar_pessoa')
    consulta = Convite.objects.all() if escopos.plataforma else Convite.objects.filter(filtro_do_escopo(escopos))
    return list(
        consulta.filter(
            _com_fim_no_futuro(), convidado_por=quem, aceito_em__isnull=True, recusado_em__isnull=True, cancelado_em__isnull=True,
            expira_em__gt=timezone.now() - RETENCAO_DE_VENCIDOS,  # o vencido aparece, marcado, para poder ser reenviado
        ).order_by('pk')
    )


def _convite_de_quem_convidou(quem, convite_id):
    """Só quem convidou mexe no convite; outro id, 404. Trava a linha e recusa o que já foi respondido."""
    convite = Convite.objects.select_for_update().get(pk=convite_id, convidado_por=quem)
    _exigir_em_aberto(convite)
    return convite


def cancelar(quem, convite_id):
    with transaction.atomic():
        convite = _convite_de_quem_convidou(quem, convite_id)
        convite.cancelado_em = timezone.now()
        convite.save(update_fields=['cancelado_em'])
        auditar('convite_cancelado', quem, convite, convite.empresa_id)


def reenviar(quem, convite_id):
    """Renova a validade e avisa a pessoa de novo; vale também para o convite vencido que ainda não foi respondido."""
    with transaction.atomic():
        convite = _convite_de_quem_convidou(quem, convite_id)
        agora = timezone.now()
        if convite.fim is not None and convite.fim <= agora:
            raise ValidationError('O período do convite já terminou.', code='convite_vencido')
        _exigir_pode_enviar(convite)
        convite.expira_em, convite.enviado_em, convite.envios = agora + VALIDADE, agora, convite.envios + 1
        convite.save(update_fields=['expira_em', 'enviado_em', 'envios'])
        auditar('convite_criado', quem, convite, convite.empresa_id, {'pessoa_id': convite.pessoa_id, 'reenvio': True})
        _avisar(convite, Pessoa.objects.get(pk=convite.pessoa_id))
