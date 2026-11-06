from django.urls import path

from pacote import views

_FAZENDA = 'empresa/<int:empresa_id>/fazenda/<int:fazenda_id>/pacote/'

urlpatterns = [
    path(_FAZENDA + 'manifesto.json', views.pacote_manifesto, name='pacote_manifesto'),
    path(_FAZENDA + 'camadas.geojson', views.pacote_camadas, name='pacote_camadas'),
    path(_FAZENDA + 'arquivo/<str:nome>', views.pacote_arquivo, name='pacote_arquivo'),
]
