# phati | Identidade visual

Pacote de logotipo vetorial e PNG, reconstruído a partir da prancha conceitual aprovada.

## Conteúdo

- `vetores_svg/phati-horizontal.svg`: marca principal na horizontal, com letras convertidas em curvas vetoriais.
- `vetores_svg/phati-simbolo.svg`: símbolo da engrenagem com representação cartográfica e marcador de localização.
- `vetores_svg/phati-vertical.svg`: assinatura vertical.
- `vetores_svg/phati-horizontal-monocromatico.svg`: versão em uma cor.
- `vetores_svg/phati-simbolo-branco.svg`: símbolo monocromático branco para aplicação sobre fundo escuro.
- `vetores_svg/phati-app-android.svg`: ícone quadrado arredondado do aplicativo.
- `png_transparente/`: PNGs em diversas resoluções, com fundo transparente.
- `android/`: ícone do aplicativo e elementos de ícone adaptativo (foreground/background) para integração Android.
- `referencia/prancha_conceitual_original.png`: apresentação raster original, preservada para comparação.

## Atenção à fidelidade

A arte inicial foi gerada como uma imagem raster (PNG), não um projeto vetorial. Portanto, os SVGs são uma **reconstrução vetorial** dos contornos e da tipografia, não os arquivos-fonte originais. O resultado é escalável e editável por nós, mas pode apresentar pequenas diferenças da prancha. As cores foram derivadas da prancha conceitual, **não** da leitura do arquivo `tokens.css` do repositório, que não foi fornecido.

## Cores da proposta

- Verde escuro: `#1B5E3C`
- Verde médio: `#2E7D52`
- Verde claro: `#C8E6C9`
- Cinza escuro: `#424242`

As demais variações de verde nos polígonos fazem parte do símbolo e não são codificação das camadas cartográficas ou de estados do sistema. Antes da implantação, conferir contraste, tamanhos mínimos, comportamento com fundo escuro e a paleta efetiva de `tokens.css`.

## Uso sugerido

Marca horizontal: cabeçalho web, materiais institucionais e telas de acesso.
Símbolo: favicon, avatar, atalhos e espaços compactos.
Ícone Android: launcher; para ícones adaptativos, integrar as versões foreground/background com as configurações de máscara do projeto.

SVG não depende de fontes instaladas, pois a palavra «phati» foi convertida em contornos vetoriais.
