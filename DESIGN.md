# DESIGN.md — direção visual do phati

Vale para a interface web. O aplicativo Android segue as mesmas regras de cor, estado e acessibilidade com componentes nativos. Os valores vivem em `servidor/projeto/static/projeto/tokens.css`; este texto explica o uso e não repete os números, para não haver duas fontes.

## Propósito

Plataforma privada de gestão e consulta de informação territorial. A web serve a quem gere e a quem consulta, dentro da permissão efetiva de cada pessoa. Não é painel financeiro nem de máquinas. O que a pessoa precisa saber vem primeiro: em que empresa e fazenda está, o que pode fazer ali, de quando é cada dado.

## Princípios

- Aplicação de trabalho, não página de divulgação: listas, árvores, fichas e tabelas antes de cartões.
- Nenhum número inventado para preencher a tela. Faltou dado: "Sem dados", "Sem pendências.", "Sem camadas ainda.". O estado vazio é legítimo.
- Sem degradê, brilho, neon nem vidro fosco decorativos. Movimento só para mostrar relação espacial ou dar retorno, e nenhum para quem pede menos movimento.
- Fonte do sistema (`system-ui`), sem fonte remota. Ícones em SVG inline.
- O menu muda pela permissão efetiva calculada no servidor, nunca só pelo cargo. Item escondido não protege nada: a rota responde 404 a quem não pode.

## Cor

Paleta verde institucional discreta sobre fundo claro. Verde não serve de sinal para tudo.

- **Camada ≠ governança.** A cor de uma camada do mapa e a cor da situação administrativa (vigente, em análise, recusada) são dois sistemas separados, com símbolos e legendas próprios. O `tokens.css` só traz o segundo e a interface; as cores de camada, quando vierem, ficam em arquivo próprio e não reutilizam as de estado.
- **Estado = cor + ícone + texto.** Erro, aviso, informação e sucesso nunca dependem só da cor. O componente de aviso reúne os três.
- **Contraste medido, não presumido.** Cada par de cor usado em texto ou contorno é declarado em `tokens.css` por um comentário `contraste:`, e `scripts/contraste-tokens.test.js` mede: 4,5:1 para texto normal, 3:1 para texto grande e contorno de campo (WCAG 1.4.3 e 1.4.11). Token de cor fora de par precisa de `isento:` com o motivo. A primeira paleta tinha a borda de campo em 1,25:1 sobre o fundo; foi escurecida e o teste cobra a regressão.
- Nenhuma página escreve cor fora de `tokens.css`.

## Espaço, tipografia e forma

Espaçamento em 4, 8, 12, 16, 24 e 32 px. Raios de 4 e 8 px. Texto em `rem`, para o zoom do navegador funcionar. Pesos 400, 600 e 700. Alvo de toque de 44 px.

## Componentes

Botão (primário e secundário), campo com rótulo e erro ligados ao controle, aviso, estado vazio, cabeçalho de página, tabela dentro de contêiner com rolagem própria, lista de convites. Ficam em `servidor/projeto/templates/componentes/` e entram por `{% include %}` com parâmetros nomeados. Tela nova usa o que existe antes de criar outro.

## Estados

Toda tela prevê carregamento (quando assíncrona), vazio, erro e sem permissão. Sem permissão é o mesmo 404 de recurso inexistente, para não revelar o que existe. As páginas 400, 403, 403 de CSRF, 404 e 500 têm texto funcional em português e um caminho de volta. A 500 não mostra pilha nem dado interno.

## Acessibilidade e responsividade

- Meta: WCAG 2.2 AA, exceto navegação só por teclado (decisão D062). O foco continua visível em todo controle (`:focus-visible`); nenhum `outline: none` sem substituto.
- A 320 px de largura a página não rola na horizontal (WCAG 1.4.10). Em largura estreita o menu vira painel recolhível e a tabela rola dentro do próprio contêiner.
- `lang="pt-BR"`; datas em dd/mm/aaaa no fuso local.

## Casca

Faixa de topo (produto, escopo "Empresa › Fazenda", nome da pessoa, Sair), menu lateral e área de conteúdo, num molde só (`casca.html`). Páginas sem sessão (entrar, esqueci a senha, redefinição, erros) usam `publica.html`. Todo `<script>` e `<link>` dos moldes leva `{% csp_nonce_attr %}`; a política de conteúdo não aceita script ou estilo inline.

## Dados de exemplo

Código, seed, teste e captura usam só dado sintético. Nome de cliente, de fazenda ou de pessoa externa não entra no repositório nem neste arquivo, e imagem de terceiros não é copiada.

## Revisão

Cada tela passa por `web-design-guidelines` (regras fixadas, sem busca remota) e por `impeccable detect`, mais revisão humana. Os hooks do `impeccable` ficam desligados.
