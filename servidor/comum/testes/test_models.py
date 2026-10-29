import pytest

from comum.models import EventoAuditoria

pytestmark = pytest.mark.django_db


def test_hora_do_servidor_vem_do_banco_e_nao_do_chamador():
    evento = EventoAuditoria.objects.create(acao='fazenda_criada')
    evento.refresh_from_db()
    assert evento.hora_servidor is not None


def test_pessoa_e_empresa_sao_ids_sem_chave_estrangeira():
    # O registro sobrevive à pessoa e à empresa apagadas, e o papel `app` não precisa de UPDATE para a FK anular nada.
    assert not EventoAuditoria._meta.get_field('pessoa_id').is_relation
    assert not EventoAuditoria._meta.get_field('empresa_id').is_relation
