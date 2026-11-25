# DESIGN.md — direção visual da AgriOn

Vale para a interface web. A marca no produto é AgriOn; o nome do repositório, dos pacotes e das URLs segue `phati` e não aparece em tela (spec 012, R5). O aplicativo Android segue as mesmas regras de cor, estado e acessibilidade com componentes nativos.

Os valores vivem nos arquivos de token copiados do pacote de design: `servidor/projeto/static/projeto/agrion/tokens/` (`colors.css`, `typography.css`, `spacing.css`). Este texto explica o uso e não repete os números, para não haver duas fontes. A cópia é igual ao pacote, byte a byte, e um teste confere isso (`servidor/projeto/testes/test_agrion_copia.py`).

## Propósito

Plataforma privada de gestão e consulta de informação territorial. A web serve a quem gere e a quem consulta, dentro da permissão efetiva de cada pessoa. Não é painel financeiro nem de máquinas. O que a pessoa precisa saber vem primeiro: em que empresa e fazenda está, o que pode fazer ali, de quando é cada dado.

## Princípios

- Aplicação de trabalho, não página de divulgação: listas, árvores, fichas e tabelas antes de cartões.
- Nenhum número inventado para preencher a tela. Dado ausente mostra "Sem dados", "Sem informação" ou "Nunca entrou"; nunca 0 no lugar de dado ausente (spec 012, R7). O estado vazio é legítimo.
- Sem degradê, brilho, neon, ilustração nem vidro fosco decorativos. O degradê só aparece no painel de marca da entrada; o vidro fosco, só no topo e no diálogo (R10).
- Movimento só para mostrar relação espacial ou dar retorno, e nenhum para quem pede menos movimento.
- O menu muda pela permissão efetiva calculada no servidor, nunca só pelo cargo. Item escondido não protege nada: a rota responde 404 a quem não pode.

## Marca

Os arquivos de `agrion/logo/` (horizontal, símbolo e símbolo branco) entram sem redesenho. O nome "AgriOn" aparece em título de aba, e-mail, remetente, página de erro e painel de administração. "phati" não aparece em texto visível.

## Cor

Os valores estão em `colors.css` em quatro grupos: escala de verde (25 a 900), escala de cinza levemente esverdeado (0 a 900), cores de estado (vermelho, âmbar, azul e sucesso, cada um em 50, 200, 500 e 700) e cores da marca. Os nomes semânticos (`--bg-*`, `--texto-*`, `--borda-*`, `--acao-primaria*`, `--erro-*`, `--aviso-*`, `--info-*`, `--sucesso-*`) são os que os componentes usam, como diz o cabeçalho do próprio arquivo.

- **Estado = cor + ícone ou ponto + texto.** Erro, aviso, informação e sucesso nunca dependem só da cor. O componente de aviso reúne os três.
- **Camada ≠ governança.** As cores `--camada-1` a `--camada-6` são da paleta do mapa e nunca viram cor de estado. Elas são provisórias até a validação cartográfica (decisão Q25 da spec 012).
- **Contraste medido, não presumido.** Texto precisa de 4,5:1 (WCAG 1.4.3). Contorno de campo, foco e ação primária precisam de 3:1 (WCAG 1.4.11). O teste `scripts/contraste-tokens.test.js` mede os pares listados em `PARES_AGRION` (`scripts/contraste-tokens.js`). Um CSS que traga par próprio anota com `/* contraste: --a sobre --b >= N */`; cor de token fora de par precisa de `/* isento: --cor-x (motivo) */`.
- Cor literal só existe nos arquivos de token e nos CSS copiados do pacote, conferidos por hash. `camadas.css` aceita cor apenas dentro de `:root`. O teste `test_componentes.py` reprova cor literal em qualquer outro lugar.

## Tipografia

- Geist (pesos 400, 500, 600 e 700) e Geist Mono (400 e 500), servidas pelo próprio servidor a partir de `agrion/fontes/` e declaradas em `fontes.css`. Não há requisição a Google Fonts nem a CDN. Geist Mono vai em coordenadas, identificadores e código.
- A escala de `typography.css` vai de 12 px a 36 px, com o corpo da interface em 14 px. Texto em `rem`, para o zoom do navegador funcionar.
- Títulos em sentence case. Rótulo de tabela e de grupo de menu em caixa alta, 12 px.
- Datas em dd/mm/aaaa. Número com vírgula decimal, ponto de milhar e unidade depois.

## Ícones

Os ícones são do Lucide 0.469.0 (licença ISC), em SVG copiado para `agrion/icones/` (43 arquivos, os usados pelas telas). Traço de 1.75 e 16 px por padrão; 12 px nas etapas, e 14, 18 ou 20 px conforme o componente (spec 012, R4). Ícone sem texto ao lado tem `aria-label`. A template tag `icone` que os entrega por nome entra na fase 2 da spec 012.

## Espaço, forma e movimento

- Espaço em `spacing.css`: grade de 4 px com passos de 2 px, de 2 a 64 px. Raios xs, sm, md, lg e xl, e um raio total para pílulas. Cinco níveis de sombra, de xs a xl.
- Altura dos controles de 32, 36 e 44 px. Medidas de layout: sidebar de 248 px, topo de 56 px, conteúdo de até 1200 px e painel de 360 px.
- Movimento de 120 ms e 200 ms, com a curva `cubic-bezier(0.2, 0, 0, 1)`. Hover, pressionado, foco (anel do token) e desabilitado a 50% (spec 012, R9). Tudo fica desligado com `prefers-reduced-motion`.

## Componentes

Um include por componente em `servidor/projeto/templates/componentes/`, com parâmetros nomeados. A lista e as variantes vêm de `COMPONENTES.md` do pacote e da spec 012 (R14). Componente sem uso em tela não é criado. Tela nova usa o que existe antes de criar outro. Os componentes da versão anterior saem na fase 2 da spec 012.

Não há `style=` em template e não há script nem estilo inline. Estilo vem de classe `ag-*` e de `agrion-proprio.css`, carregado por último; a política de conteúdo não aceita inline (spec 012, R12).

## Layout e acessibilidade

- Meta: WCAG 2.2 AA, exceto navegação só por teclado (decisão D062). O foco fica visível em todo controle (`:focus-visible`).
- Alvo de 44 px abaixo de 64 rem e nas telas públicas; 32 ou 36 px no desktop (spec 012, R11).
- A 320 px a página não rola na horizontal. A tabela rola dentro do próprio contêiner. Abaixo de 64 rem, a sidebar vira gaveta de 280 px.
- `lang="pt-BR"`.

## Casca e telas

- Casca (`casca.html`): sidebar com logo, seletor de escopo e menu agrupado, mais topo de 56 px com a trilha da página e área de conteúdo. O menu mostra só o que a permissão efetiva permite (R16).
- Páginas sem sessão (entrar, esqueci a senha, redefinição, erros) usam `publica.html`, com molde de duas colunas. O painel de marca some abaixo de 56 rem.
- Todo `<script>` e `<link>` dos moldes leva `{% csp_nonce_attr %}`.

## Estados

Toda tela prevê carregamento (esqueleto em lista e painel; spinner só em botão), vazio, erro e sem permissão. Sem permissão é o mesmo 404 de recurso inexistente, para não revelar o que existe. As páginas 400, 403, 403 de CSRF, 404 e 500 têm texto funcional em português e um caminho de volta. A 500 não mostra pilha nem dado interno.

## Textos

Português do Brasil, frases curtas, sem exclamação, emoji ou texto de exemplo. Botão com verbo no infinitivo, e um botão primário por área.

## Dados de exemplo

Código, seed, teste e captura usam só dado sintético. Nome de cliente, de fazenda ou de pessoa externa não entra no repositório nem neste arquivo, e imagem de terceiros não é copiada.

## Origem e cópia

O pacote de design AgriOn fica num repositório privado, fora deste. Do pacote entram só tokens, CSS, fontes, ícones usados e logos; `fonts.css` e `styles.css` do pacote não entram, porque importam Google Fonts. Os hashes de cada arquivo copiado estão em `servidor/projeto/testes/agrion_manifesto.sha256`.

## Revisão

Cada tela passa por `web-design-guidelines` (regras fixadas, sem busca remota) e por `impeccable detect`, mais revisão humana. Os hooks do `impeccable` ficam desligados.
