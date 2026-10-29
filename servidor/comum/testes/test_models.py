import pytest
from django.db import connection

from comum.models import EventoAuditoria

pytestmark = pytest.mark.django_db


def test_hora_do_servidor_vem_do_padrao_do_banco():
    # INSERT sem a coluna: só o default do banco pode preenchê-la (um default do Python não passaria por aqui).
    with connection.cursor() as consulta:
        consulta.execute("INSERT INTO evento_auditoria (acao, alvo_tipo, detalhes) VALUES ('fazenda_criada', '', '{}') RETURNING hora_servidor")
        assert consulta.fetchone()[0] is not None


def test_pessoa_e_empresa_sao_ids_sem_chave_estrangeira():
    # O registro sobrevive à pessoa e à empresa apagadas, e o papel `app` não precisa de UPDATE para a FK anular nada.
    assert not EventoAuditoria._meta.get_field('pessoa_id').is_relation
    assert not EventoAuditoria._meta.get_field('empresa_id').is_relation
