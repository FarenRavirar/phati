# Contrato do pacote offline por fazenda (spec 004b, R6)

Contrato entre o servidor e o aplicativo Android. O servidor entrega, por fazenda, a **versão vigente** do pacote: um
diretório com `manifesto.json` e arquivos PMTiles. O aplicativo guarda o diretório inteiro e lê os arquivos como locais.

## Formato

- `manifesto.json`, validado pelo esquema `servidor/pacote/esquema_manifesto.json` (JSON Schema gerado de `pacote/manifesto.py`;
  um teste confere que o arquivo não saiu do modelo). Campos: `formato_versao`, `fazenda_id`, `versao`, `gerado_em`,
  `zoom_maximo_ortofoto`, `arquivos[]` (nome, papel `fundo` ou `ortofoto`, bytes, SHA-256, zoom mínimo e máximo, atribuição,
  licença, `capturada_em` só na ortofoto) e `camadas[]` (identificador, revisão vigente, data).
- Campo desconhecido é recusado (`extra='forbid'`): **o pacote não leva documento** (RF-09). Documentos e rasters de valor só online.
- O aplicativo recusa `formato_versao` que não conhece, confere bytes e SHA-256 de cada arquivo antes de usar e troca a versão
  de uma vez (baixa a nova ao lado, confere, só então apaga a anterior).
- Versões: número inteiro crescente por fazenda; uma só é vigente. A versão nova nunca apaga a anterior no servidor, então o
  aplicativo baixa os arquivos com `?versao=<versao do manifesto>` e uma versão nova no meio do download não mistura bytes.

## Rotas (todas sob `/empresa/<id>/fazenda/<id>/pacote/`)

| Rota | Exige | Observação |
|---|---|---|
| `manifesto.json` | `baixar_pacote_offline` | 403 com alcance e sem a ação; 404 sem alcance (igual a fazenda inexistente) |
| `camadas.geojson` | `baixar_pacote_offline` | só as revisões vigentes que a pessoa pode ver, pela mesma função da API de camadas |
| `arquivo/<nome>?versao=N` | `ver` | `nome` precisa estar no manifesto; `N` é o `versao` do manifesto baixado (sem o parâmetro, a vigente); aceita `Range` (206 e 416), `If-Range` e `If-None-Match` (ETag = SHA-256) |

Todas respondem `Cache-Control: private, no-cache`. **Limite registrado:** quem tem `ver` baixa os bytes de fundo e ortofoto,
porque a web os lê pelos mesmos arquivos (D097).

## Estilo compartilhado

`servidor/projeto/static/projeto/estilo_base.json` (a web lê o mesmo arquivo). `{pacote}` é o diretório local da versão. O aplicativo usa `pmtiles://file://{pacote}/<arquivo>`
no MapLibre Native. Só propriedades comuns a GL JS e Native (T0.7): `background`, `fill`, `line` e `raster` básicos;
proibidos `fill-layer-opacity`, `line-layer-opacity` e os `*-layer-blend`. Versões fixas do renderizador: GL JS 6 e a do Native
registrada na T0.7 da `tasks.md` da 004b (ainda a fixar).

## Consulta

A ordem das camadas e a regra de qual feição responde ao toque são do código do cliente, não do estilo: o aplicativo ordena a
consulta no código, como a web (`mapa.js`). A ortofoto nunca devolve valor de raster.

## Regras para o fundo Google (R21 a R23, código no aplicativo)

- **R21:** respeitar `Cache-Control` e `ETag` do Google; reaproveitar o que está fresco (24 h); guardar o token da sessão até
  uma hora antes do `expiry`; tiles de 512 px; só carregar o satélite quando a pessoa o liga; descartar a sessão recusada (401).
- **R22:** sem rede, manter o Google só enquanto os tiles da vista estão frescos; o primeiro tile sem cache fresco troca a vista
  inteira para o fundo próprio; nunca servir tile expirado; os dois fundos nunca aparecem juntos. Falta medir no aparelho.
- **R23:** o pacote e o estilo nunca citam o Google; a fonte do Google não entra em região offline do `OfflineManager`.

## Atribuição e licença

O fundo aberto é derivado do OpenStreetMap (ODbL 1.0): "© OpenStreetMap contributors" fica visível perto do mapa. O meio de
oferecer os dados sob pedido ainda não foi decidido (T0.5).

## Pacote de referência

`servidor/pacote/referencia/` (sintético, minúsculo, no centro de teste da 004): gerado pelo comando real
`gerar_pacote_fazenda`. `test_referencia.py` o valida contra o esquema. Use `--caixa=` com igual: o valor começa com "-".
