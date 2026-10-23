from wsgiref.util import setup_testing_defaults

import pytest

from projeto.wsgi import application


# O ciclo de requisição do Django fecha conexões antigas, então o teste precisa liberar o banco.
@pytest.mark.django_db
def test_aplicacao_wsgi_responde_404_enquanto_nao_ha_rota():
    # Sem ROOT_URLCONF a aplicação devolvia 500 (medido no contêiner); com `urlpatterns` vazio, 404.
    ambiente = {'REQUEST_METHOD': 'GET', 'PATH_INFO': '/'}
    setup_testing_defaults(ambiente)
    estados = []

    def iniciar_resposta(estado, cabecalhos, informacao=None):
        estados.append(estado)
        return lambda corpo: None

    list(application(ambiente, iniciar_resposta))
    assert estados[0].startswith('404')
