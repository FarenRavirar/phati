from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, models, transaction

from identidade import cpf as modulo_cpf


class GerentePessoa(models.Manager):
    def criar(self, nome, email, cpf, empresa_origem=None):
        """Cria a pessoa sem senha utilizável; a senha temporária entra em `senha.emitir_senha_temporaria`."""
        cpf_normalizado = modulo_cpf.normalizar_cpf(cpf)
        validate_email(email)
        pessoa = self.model(
            nome=nome,
            email=email,
            cpf_busca=modulo_cpf.chave_de_busca(cpf_normalizado),
            cpf_cifrado=modulo_cpf.cifrar(cpf_normalizado),
            empresa_origem=empresa_origem,
        )
        pessoa.set_unusable_password()
        try:
            with transaction.atomic(using=self.db):
                pessoa.save(using=self.db, force_insert=True)
        except IntegrityError:
            if not self.filter(cpf_busca=pessoa.cpf_busca).exists():
                raise  # outra restrição (por exemplo, empresa de origem inexistente): erro verdadeiro
            raise ValidationError('CPF já cadastrado.', code='cpf_duplicado') from None
        return pessoa


class Pessoa(AbstractBaseUser):
    """Usuário do sistema, identificado pelo CPF (R1). Sem permissão própria: acesso decide `pode()` (Fase 3)."""

    # `password` e `last_login` são nomes impostos por AbstractBaseUser; só a coluna fica em português.
    password = models.CharField('senha', max_length=128, db_column='senha')
    last_login = models.DateTimeField('último acesso', null=True, blank=True, db_column='ultimo_acesso')

    nome = models.CharField(max_length=200)
    email = models.EmailField()
    cpf_busca = models.CharField(max_length=64, unique=True)
    cpf_cifrado = models.TextField()
    # Nula para o Administrador da plataforma, que não pertence a empresa (comando de T5.4).
    empresa_origem = models.ForeignKey('territorio.Empresa', null=True, blank=True, on_delete=models.PROTECT)
    senha_temporaria_ate = models.DateTimeField(null=True, blank=True)
    deve_trocar_senha = models.BooleanField(default=False)
    falhas_consecutivas = models.PositiveIntegerField(default=0)
    bloqueada_ate = models.DateTimeField(null=True, blank=True)
    administrador_plataforma = models.BooleanField(default=False)

    objects = GerentePessoa()
    USERNAME_FIELD = 'cpf_busca'

    def __str__(self):
        return self.nome  # o padrão do Django mostraria `cpf_busca` (índice cego do CPF) no painel

    def get_short_name(self):
        return self.nome

    class Meta(AbstractBaseUser.Meta):
        db_table = 'pessoa'


class PedidoRedefinicao(models.Model):
    """Pedido de redefinição (R5). Guarda só o SHA-256 do segredo do link; `tentativas` conta o limite de 5 por pedido."""

    pessoa = models.ForeignKey(Pessoa, on_delete=models.CASCADE)
    hash_segredo = models.CharField(max_length=64, unique=True)
    # SET_NULL: PROTECT impediria apagar quem pediu a própria redefinição (o pedido também cai em cascata por `pessoa`).
    solicitado_por = models.ForeignKey(Pessoa, null=True, on_delete=models.SET_NULL, related_name='+')
    expira_em = models.DateTimeField()
    usado_em = models.DateTimeField(null=True, blank=True)
    tentativas = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = 'pedido_redefinicao'


class AcessoAplicativo(models.Model):
    """Acesso do aplicativo: segredo opaco rotativo (R15). `entrada_em` é herdado na rotação: dele vem o teto absoluto de 30 dias."""

    pessoa = models.ForeignKey(Pessoa, on_delete=models.CASCADE)
    hash_segredo = models.CharField(max_length=64, unique=True)
    dispositivo = models.CharField(max_length=200)
    entrada_em = models.DateTimeField()
    expira_em = models.DateTimeField()
    revogado_em = models.DateTimeField(null=True, blank=True)
    # Preenchido quando a renovação troca este segredo por outro; sem ele, `revogado_em` veio de sair ou de troca de senha.
    substituido_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'acesso_aplicativo'
