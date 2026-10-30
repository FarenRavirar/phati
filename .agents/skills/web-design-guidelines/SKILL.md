---
name: web-design-guidelines
description: Revisa código de UI contra as Web Interface Guidelines da Vercel (regras fixadas em `regras.md`). Use ao pedir "revisar a UI", "checar acessibilidade", "auditar design".
metadata:
  author: vercel
  version: "1.0.0"
  argument-hint: <arquivo-ou-padrão>
---

# Web Interface Guidelines (cópia fixada)

Origem: `vercel-labs/agent-skills`, skill `web-design-guidelines` (commit `1a2c79d4e6c4`), licença MIT declarada no README do repositório. As regras vêm de `vercel-labs/web-interface-guidelines`, commit `434b7f913646`, copiadas para `regras.md`.

Mudança em relação ao original, por segurança (`AGENTS.md` §Segurança com IA, práticas 1 e 6): a skill original busca as regras por `WebFetch` a cada uso; aqui **não há busca remota**. Atualizar `regras.md` exige ler o diff e trocar o commit acima.

## Como usar

1. Ler `regras.md`, na mesma pasta.
2. Ler os arquivos pedidos (ou perguntar quais).
3. Conferir contra as regras e responder no formato `arquivo:linha`, agrupado por arquivo.

## Regras que não valem no phati

- **Teclado** (`onKeyDown`, alternativa de teclado para gesto): fora de escopo por D062. Foco visível (`:focus-visible`) continua valendo.
- **React/Next** (hidratação, `onChange`, `<Link>`, `nuqs`): a stack é Django com JS leve.
- **Texto em inglês** (Title Case, `&` no lugar de "e", aspas curvas inglesas): o produto é pt-BR; aplicar só pontuação e clareza que valem em português.
