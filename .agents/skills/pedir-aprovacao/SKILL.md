---
name: pedir-aprovacao
description: Procedimento para pedir aprovação ao mantenedor do phati — o formato do bloco "APROVAÇÃO NECESSÁRIA", o que cada campo precisa conter, e a mecânica de worktree e de pacote apt/lib nova. Use quando for pedir autorização para commit, merge, deploy, escrita na VM, SQL write, mudança de DNS/tunnel, criação de worktree ou instalação de pacote/biblioteca nova — ou quando um gate bloquear uma ação e mandar pedir aprovação. A LISTA do que exige aprovação fica no `AGENTS.md` §Autorização, não aqui; aqui está só o como pedir.
---

# Pedir aprovação — procedimento

O `AGENTS.md` §Autorização guarda **o que** exige aprovação e a regra de que ela
vale por ação (nunca por sessão nem por PR). Este documento guarda **como pedir**.

Três camadas mecânicas já cobram isso sem depender de memória: as regras
declarativas de cada harness (`permissions.ask`/`deny` no Claude Code,
`.codex/rules/governanca.rules` no Codex, `permission.bash` no OpenCode) e o
hook `autorizacao-gate.js`, que alcança as formas que elas não alcançam
(caminho absoluto, `git -C`, comando aninhado em `bash -lc`). Quando um deles
bloquear, o motivo do deny já diz qual regra é — e é aqui que está o formato da
resposta.

## O formato

```text
## APROVAÇÃO NECESSÁRIA

Ação: [o que será feito]
Motivo: [por que]
Risco: [o que pode dar errado]
Rollback: [como desfazer]
Escopo: [qual app/projeto/pacote/gate]

Comandos:
1. ...

Posso prosseguir?
```

O que cada campo precisa carregar para o pedido ser respondível:

- **Ação** — o comando exato, não a intenção. "Commitar as 3 correções de review
  na branch `chore/101`" é ação; "finalizar a fase" não é.
- **Motivo** — por que agora, e o que trava se não for feito.
- **Risco** — o que quebra se der errado, em consequência observável (produção
  fora do ar, dado perdido, PR ilegível), não em termo técnico solto.
- **Rollback** — o comando que desfaz. Se não houver, dizer que não há: é
  exatamente a informação que decide o "sim" ou "não".
- **Escopo** — qual app, pacote ou gate. Delimita o que a aprovação cobre; ela
  não se estende ao que ficou de fora.
- **Comandos** — numerados, na ordem, um por linha.

**Pedido de lib/pacote não precisa do bloco completo** — basta uma pergunta
direta, salvo quando for `apt` ou infra de VM. O que ela precisa ter está na
seção de pacote, abaixo.

## Worktree

Worktree **não é fallback automático**. Antes de qualquer `git worktree
add|move|remove`, o pedido de aprovação nominal precisa responder, nesta ordem:

1. **Por que o cwd não pode ser usado.** É a pergunta que o mantenedor faz
   primeiro, e sem ela o pedido volta.
2. **O caminho exato** que será criado (`../phati-<escopo>`, `C:\tmp\...`).
3. **O que será criado e removido.**
4. **Como o trabalho volta ao cwd** — commit, stash identificado, ou cherry-pick.

Vale igual quando o objetivo é contornar `cherry-pick`/rebase/merge/checkout
bloqueado, preservar estado alheio ou permitir trabalho paralelo.

Depois de aprovado: `git worktree add ../phati-<escopo> <branch>`, nunca
checkout na mesma pasta enquanto outro agente roda ali. `node_modules` só
reinstala no worktree se for rodar build/test/dev ali — o store global do pnpm
evita duplicar peso. Remoção só depois de confirmar o worktree limpo e o
trabalho preservado em commit ou stash identificado; nunca `--force` por
inferência.

`git worktree list` e inspeção read-only continuam livres, sem aprovação.

## Pacote `apt` ou biblioteca nova

A barreira não é "nunca sem aprovação prévia" — é **"nunca sem perguntar
primeiro"**. O agente pode introduzir lib nova quando a tarefa precisar, desde
que pare e pergunte antes, informando:

- qual pacote/lib e a versão;
- por que é necessário;
- **alternativa já existente no repo**, se houver — e se a lib for redundante
  com algo já usado, ou divergir da stack canônica, isso vai na própria
  pergunta, não fica para o mantenedor descobrir;
- tamanho/impacto aproximado.

Vale igual para dependência de app/projeto e para `apt` — inclusive os casos que
parecem triviais: `git`, `jq`, `tree`, `p7zip-full`, `postgresql-client`, `curl`,
`ca-certificates`. Só instala depois da resposta. Para `apt`, o comando após
aprovação é:

```bash
sudo apt-get update && sudo apt-get install -y <pacote>
```

**A aprovação de uma lib não se estende.** Ela não autoriza instalar serviço
persistente novo, alterar arquitetura, mexer em DNS/tunnel ou executar deploy —
cada um segue exigindo aprovação própria e nominal.

## O erro que este procedimento existe para evitar

Aprovação pedida sobre opção **não medida**. O `AGENTS.md` §Evidência item 3 é
explícito: opção oferecida ao mantenedor é opção verificada. O incidente que
originou a regra (2026-08-08, spec 090) foi um pedido para "apagar os três
comentários e refazer o smoke" com custo inventado — dois triggers recusavam o
`DELETE`, e a opção nunca existiu. Antes de listar alternativas no bloco, medir
cada uma; a que não foi medida sai da lista, ou vai marcada "não medi o
custo/viabilidade".

Vale também para o próprio erro do agente: quando a limpeza exige ação de
aprovação (escrita em produção, por exemplo), o agente chega com a correção
**medida e pronta** e pede a aprovação da escrita — não apresenta o próprio erro
como bifurcação para o mantenedor decidir.
