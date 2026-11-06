# AgriOn | Identidade visual

Pacote da identidade visual definitiva da marca **AgriOn**, para a plataforma de gestão e inteligência territorial.

## O que foi mantido

- **Símbolo original intacto**: engrenagem, representação cartográfica e marcador de localização, sem redesenho geométrico.
- **Paleta original intacta**: verdes institucionais e cinza escuro, com uso obrigatório do verde institucional `#1B5E3C` na palavra **On**.
- Variantes horizontal, vertical, monocromática, símbolo isolado e aplicativo Android.
- Resoluções dos PNGs da edição anterior, inclusive tamanhos pequenos e recursos do Android.

## O que mudou

- Nome, metadados, arquivos, documentação e textos das assinaturas atualizados para **AgriOn** (A e O maiúsculos).
- **Regra obrigatória da assinatura colorida:** **Agri** em `#424242` e **On** em `#1B5E3C`. O ponto do **i** também é cinza, pois pertence a **Agri**.
- Os logotipos com texto foram redesenhados tipograficamente em **curvas vetoriais** usando um estilo sem serifa geométrico com peso forte. É impossível trocar simplesmente as letras antigas, também em curvas, sem refazer os novos glifos.
- A prancha conceitual foi reconstruída integralmente com a nova marca e adicionada em SVG e PNG, sem deixar referências visíveis à marca anterior.

## Estrutura

- `vetores_svg/agrion-horizontal.svg`: assinatura principal vetorial.
- `vetores_svg/agrion-vertical.svg`: assinatura empilhada vetorial.
- `vetores_svg/agrion-horizontal-monocromatico.svg`: variante de uma cor.
- `vetores_svg/agrion-simbolo.svg`: símbolo original vetorial.
- `vetores_svg/agrion-simbolo-branco.svg`: símbolo branco para superfícies escuras.
- `vetores_svg/agrion-app-android.svg`: ícone do aplicativo Android.
- `png_transparente/`: versões PNG transparentes, de 32 a 2048 px.
- `android/`: launcher PNG e SVG e camadas para ícone adaptativo Android (foreground/background).
- `referencia/`: prancha de apresentação original aprovada, atualizada em PNG com correção localizada da cor de **On** (sem alteração de layout), e uma reconstrução vetorial da prancha em SVG.

## Paleta da identidade visual

| Token conceitual | Hex |
| --- | --- |
| Verde escuro institucional e palavra **On** | `#1B5E3C` |
| Verde médio | `#2E7D52` |
| Verde claro | `#C8E6C9` |
| Cinza escuro e palavra **Agri** | `#424242` |

Os verdes internos do mapa compõem a ilustração da marca. **Não devem ser reutilizados automaticamente** como cores de estados administrativos ou de camadas no sistema. A interface continua sujeita aos pares de contraste definidos em `tokens.css` e às regras do `DESIGN.md`.

## Observações técnicas

1. Os SVGs principais possuem contornos de letras e formas vetoriais independentes de fontes remotas ou instaladas.
2. A identidade tem origem numa prancha raster; os SVGs desta distribuição são reconstruções vetoriais. Esta edição preserva fielmente os contornos existentes do símbolo, com o nome AgriOn em curvas vetoriais.
3. O ícone Android foi mantido igual, já que não contém o nome; apenas os nomes dos arquivos e metadados mudaram.
4. Para ícones adaptativos, inserir `foreground`/`background` no projeto Android e configurar os recursos XML conforme o pacote usado pelo aplicativo.
5. Os PNGs de logotipos com nome foram renderizados de seus SVGs vetoriais.
6. **Não foi feita análise de marca registrada nem disponibilidade de domínio.**

## Revisão da cor do nome

- Hexadecimal final de **On**: `#1B5E3C` (RGB 27, 94, 60).
- Hexadecimal de **Agri** (incluindo o ponto do i): `#424242` (RGB 66, 66, 66).
- A prancha PNG reproduz a arte aprovada na conversa anterior, alterando exclusivamente a tonalidade da palavra **On** em suas três ocorrências.
- As variações monocromáticas continuam sendo de uma única cor, por definição.
