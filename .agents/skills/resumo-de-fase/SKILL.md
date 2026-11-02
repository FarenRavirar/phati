---
name: resumo-de-fase
description: Escreve o resumo de produto de uma fase de spec para a Tati (sem código, só o que a pessoa faz, quem pode o quê, decisões e pendências). Use quando o mantenedor disser que uma fase terminou, ou pedir "resumo da fase N", "resumo para a Tati" ou "o que foi a fase N".
---

# Resumo de fase para a Tati

Texto que sai do chat e vai para uma pessoa de produto: prosa normal em português, não `caveman`. Nada de código.

## Entrada

Spec e fase. O mantenedor manda "terminei a fase N" (spec = a que está em andamento em `specs/README.md`) ou "resumo da spec NNN fase N". Se a spec ou a fase não estiver clara, perguntar uma vez.

## Fonte (medir, não lembrar)

1. `specs/NNN-slug/spec.md`: os requisitos `R` da fase e os critérios de aceite `A` ligados a eles.
2. `specs/NNN-slug/tasks.md`: o bloco da fase, com o que foi feito, o que falta e o que ficou decidido.
3. `.specify/memory/decisions.md`: só as decisões `D` citadas pelos requisitos da fase.
4. Estado da entrega: `rtk git log` e `gh pr view` da branch da fase. Dizer só em palavras: "em desenvolvimento", "em revisão" ou "mesclada". Nunca SHA, nome de branch nem número de PR.

Afirmação sem fonte não entra. O que não deu para medir vai para "O que falta fechar", dito assim.

## Formato

```text
Spec NNN · <nome da spec> — Fase N: <título da fase>

<2 a 3 frases: o problema que a fase resolve para quem usa o produto.>

O que dá para fazer
- <ação do ponto de vista de quem usa, uma por linha>

Quem pode o quê
- <papel e limite, em português simples>

Decisões que valem para o produto
- <decisão, com o motivo em uma frase>

O que falta fechar
- <pendência, e quem decide ou responde: Tati, mantenedor ou revisão>
```

Seção sem conteúdo some. Pergunta que a Tati precisa responder vai em "O que falta fechar", com as opções.

## Regras

- **Só produto.** Sem caminho, função, tabela, rota, sigla técnica, `R`/`A`/`D` com número, nome de biblioteca ou comando. Traduzir: "CPF", "senha temporária", "convite pendente" são do produto; `RLS`, "cascata", "fila de e-mail" viram o efeito que a pessoa vê.
- **Nome de cliente, de fazenda e de pessoa externa nunca entra** (`AGENTS.md`, repositório público).
- **Cargos como o produto os chama:** Administrador, Curador, Técnico, Usuário; Administrador da plataforma quando for o caso.
- **Frases curtas, verbo no começo da ação.** Sem abertura nem fecho ornamental, sem "robusto", "poderoso", "seamless". Aplicar `humanizer` só nos padrões que valem em português.
- **Não prometer.** "Falta rodar o teste final" é fato; "vai ficar pronto amanhã" não é.
- **Escopo da fase.** O que outra fase entrega não entra, mesmo que a spec o cite.
- **Pendência de decisão do mantenedor** (custo, infraestrutura, prioridade) aparece como tal, nunca como decisão tomada.
- Entregar o texto no chat, pronto para copiar. Não salvar arquivo nem commitar.
