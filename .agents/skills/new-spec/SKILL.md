---
name: new-spec
description: Cria o esqueleto de uma spec SDD do phati em specs/NNN-modulo-slug/ com spec.md, plan.md e tasks.md a partir dos templates. Use ao iniciar qualquer trabalho SDD Completo (compartilhado, infra, migration, auth, importador, SEO, feature grande).
---

# Nova spec SDD

## Quando usar

Use em trabalho SDD Completo: `packages/*`, infra, tunnel/DNS, `accounts.`, SSO, CI/CD, migration, banco, dados pessoais, importador, contrato público/API, SEO estrutural, feature grande, refator grande, auditoria ou revisão que possa gerar tasks, reviews ou débitos.

## Regras

* Spec antes de código.
* Não implemente nesta skill.
* Jamais faça commit, push, merge ou PR sem autorização explícita do usuário.
* Não avance fase sem autorização.
* Se houver dúvida, pergunte em tom simples, com opções e impacto de cada opção.
* Não chute. Registre evidência.
* Sem solução técnica no `spec.md`; isso é `plan.md`.
* Tasks pequenas, verificáveis e rastreáveis.
* **Toda fase termina com gate de cruzamento (obrigatório).** Ver §Gate de fase abaixo.
* **Requisito recebe ID (`R1`, `R2`…) e é citado nominalmente** pela task que o implementa e pelo gate que o valida. Requisito sem ID não é rastreável; task que não cita requisito nenhum é suspeita de estar fora do escopo aprovado.
* **Correção de review de bot é documentada em comentário NO PRÓPRIO CÓDIGO, referenciando a origem** — não em sessão, não em arquivo de review. Ver §Review de bot abaixo.
* Nunca responder, comentar, resolver thread ou reagir no PR (`AGENTS.md`: o agente não escreve na conversa do PR; isso é do mantenedor).
* **Levantar decisões de arquitetura/produto ANTES de escrever os três arquivos.** Se a spec tem ponto que muda o raio da implementação (rota, pacote compartilhado, fórmula/cálculo, escopo de sort/filtro), perguntar via `AskUserQuestion` (lotes de até 4) **na hora**, antes de redigir. **Spec só está pronta quando zero decisão de produto/arquitetura ficou em aberto** — "decisão pendente" dentro do arquivo final é sinal de spec incompleta, não de spec entregável. Exceção: achado técnico que só aparece **durante** a investigação pode gerar pergunta nova a qualquer momento — mas sai do "pendente" assim que respondida.
* Débito acionável que sair desta spec vai pra `specs/backlog.md`.
* **Débito ou achado que toca frontend/backend do escopo da spec é resolvido NA PRÓPRIA SPEC**, não empurrado pra backlog "pra depois". O agente não decide adiar; na dúvida, pergunta ao mantenedor (regra do mantenedor, 2026-07-25). Backlog é pra o que o mantenedor mandou sair, ou pro que é genuinamente de outra frente.
* Atualize sessão em `sessoes/`.
* Atualize `project-state.md` só se mudar estado operacional.

## Gate de fase (obrigatório em toda spec)

**Por que existe.** `tasks.md` é resumo. Quem implementa — em especial agente que entra frio numa fase, sem o contexto da investigação — tende a tratar a checklist como a verdade completa e perder o que só está escrito no `spec.md`/`plan.md`: requisito, decisão do mantenedor, armadilha já investigada, achado com arquivo:linha. O resultado é implementação que "fecha todas as tasks" e ainda assim não atende a spec. O gate fecha esse buraco.

**Regra.** Toda fase de `tasks.md` termina com **duas** tasks, nesta ordem:

1. 🔁 **GATE DE FASE** — penúltima task, antes do PR.
2. Verde local (`rtk tsc`/lint/test, `pnpm verify:api` quando aplicável) + PR.

O gate **nomeia** o que reler — nunca "revisar a spec" genérico, que não é verificável:

```markdown
- [ ] TN.x — 🔁 **GATE DE FASE — cruzar com `spec.md` e `plan.md` antes de fechar.**
  Reler os requisitos **R3, R4 e R9** da `spec.md` e as seções §"<nome exato>" e
  §"<nome exato>" do `plan.md`, e confirmar item por item que a implementação bate.
  Verificar em especial: <2 a 5 pontos concretos e verificáveis desta fase —
  travas objetivas, decisões do mantenedor, armadilhas registradas na investigação>.
  Divergência achada aqui = corrigir antes do PR, ou perguntar ao mantenedor se a
  spec é que está errada — nunca seguir o `tasks.md` contra a `spec.md` calado.
```

**O que o gate exige, sem exceção:**

* Achou divergência → **corrigir antes do PR**. Se a dúvida for se a spec está errada, **perguntar ao mantenedor**.
* **Nunca** seguir o `tasks.md` contra `spec.md`/`plan.md` em silêncio.
* **Nunca** fechar fase com requisito não atendido, nem "atendido em parte" (`AGENTS.md` §Conclusão de Tarefas proíbe conclusão parcial).
* Preferir ponto **objetivamente verificável** a julgamento: `git diff` sem caminho proibido, `package.json` sem dependência proibida, ordem de rota no router, ausência de N+1 por contagem de chamadas, campo sem HTML. Ponto que só se checa "no olho" vira smoke visual explícito.

**Gate final da última fase** (validação/fechamento) é mais amplo: percorrer **todos** os requisitos e critérios de aceite um por um, mais os gaps do §Problema, e reconferir as travas objetivas — não assumir que os gates de fase já cobriram. Requisito não atendido = spec não está pronta, mesmo com todas as tasks marcadas.

**Cobertura de teste.** A última fase também audita, por tabela, que cada arquivo novo/alterado tem `.test` correspondente, separando **novos** de **estendidos** e nomeando o caminho de cada um. Arquivo tocado sem teste = task reaberta.

## Registro anti-compactação (obrigatório em toda fase)

**Por que existe.** Sessão longa é compactada: o histórico vira resumo e o agente seguinte — ou o mesmo agente, depois do corte — perde o que não estiver escrito em arquivo. O que se perde primeiro é justamente o mais caro de redescobrir: a **medição que derrubou uma hipótese** e a **armadilha que já custou uma volta**. A checklist sobrevive; o "por que não é do jeito óbvio" não. Resultado medido nesta base (spec 102 T4.2): três defeitos de proxy foram encontrados, corrigidos e **reencontrados** depois da compactação, porque só estavam no chat.

**Regra.** O achado vai para arquivo **no mesmo turno** em que é medido — nunca "depois, quando fechar a fase". Dois destinos, e a escolha não é livre:

| O achado | Vai para |
|---|---|
| Explica por que o **código** é assim | Comentário no próprio código, no ponto exato |
| Muda o **estado ou o contrato** da task | Bloco da task em `tasks.md` (reescrito, não anexado) |

Na dúvida, os dois: o comentário sobrevive ao refactor, o `tasks.md` sobrevive ao `git checkout`.

**O que obriga registro, sem exceção:**

* **Forma óbvia que não funciona.** A que o próximo agente vai tentar primeiro. Escrever o que ela produz de errado, não só qual é a certa — senão ele "corrige" de volta. Ex.: `app.use('/api', proxy)` remove o prefixo e o backend recebe `/v1/health`.
* **Medição que contradiz o que a spec dizia.** A correção entra no lugar do texto errado, marcando que o registro anterior estava errado. Não apagar em silêncio: o próximo agente precisa saber que aquilo já foi tentado.
* **Valor que parece constante e não é.** Env, CIDR, nome de container, porta — com produção e homologação lado a lado quando divergem. Hardcodar o valor de um ambiente faz o outro escrever no banco errado.
* **Bug latente achado de passagem**, com a medição que o revelou e o que aconteceria se não fosse corrigido — em especial o que **falha em silêncio**, sem erro de boot.
* **Decisão de não fazer algo**, com o motivo medido. Sem isso o próximo agente "completa" o trabalho e quebra o que estava intencionalmente de pé.

**Trava de qualidade do registro:** vale o que é **verificável** — comando rodado e o que devolveu, `arquivo:linha`, contagem. "Cuidado com o proxy" não é registro; "`pathFilter` em array recusa glob misturado com caminho plano (medido em `dist/path-filter.js`), e o sintoma é não casar nada" é.

**Como não inchar o arquivo** (`AGENTS.md` §Conclusão de Tarefas: doc descreve estado, não histórico): reescrever o bloco da task, nunca anexar "estado em <data>" embaixo do anterior. Medir com `rtk git diff --stat` ao fechar — doc de estado só com inserções é sinal de empilhamento.

## Review de bot: comentário no código, não em documento

Correção vinda de revisor automático (CodeRabbit, Codex, Sonar, Amazon Q, Snyk, GitHub Advanced Security) é documentada **no próprio código, no ponto corrigido**, referenciando a origem. Não vira registro em sessão nem em arquivo de review.

**Motivo:** o comentário fica onde o próximo agente vai ler — junto do código que ele pode desfazer sem saber por quê. Registro em documento separado se perde; comentário inline sobrevive ao refactor e explica a decisão no lugar em que ela importa. É a mesma razão da regra de `AGENTS.md` que proíbe apagar comentário explicativo em edição posterior.

**Formato já usado nesta base** (padrão consolidado, seguir):

```ts
// Achado real (review PR #201, Codex, P1): /ingest validava source_platform
// contra IMPLEMENTED_SOURCE_PLATFORMS (só as 5 fontes com scraper automático)
// — vestígio da Fase 5. Depois da Fase 6 (registry em banco), qualquer site
// cadastrado só via /gestao/plataformas nunca teria adapter em ADAPTERS, então
// /parse-html funcionava mas /ingest sempre devolvia 400.
```

Variações válidas, todas em uso: `Achado real (review PR #NNN, <bot>, <severidade>)`, `Achado de review PR #NNN (<bot>)`, `Achado de review PR #NNN (<bot>, nitpick)`.

**O comentário precisa conter:**

* **origem**: número do PR + qual bot (+ severidade quando o bot dá: `P1`/`P2`/`nitpick`);
* **o que estava errado de fato** — não "corrigido conforme review", que não ensina nada;
* **por que a correção é essa** — o raciocínio que o próximo agente precisaria reconstruir sozinho.

Vale igual em teste, migration (dentro do `@description` do header ou como comentário SQL), `Dockerfile` e config — não só em `.ts`.

**O que NÃO fazer:**

* comentário genérico (`// fix review`, `// ajuste do CodeRabbit`) — não documenta decisão nenhuma;
* apagar o comentário num refactor posterior; se a razão mudou, **reescrever** pra refletir a decisão atual, citando a origem nova (`AGENTS.md`);
* registrar a correção só em `tasks.md`/sessão e deixar o código sem explicação;
* escrever qualquer coisa na conversa do PR.

**O que continua em documento:** achado de review que **não** vira código agora — descartado (com o porquê) ou virou débito — vai pra `tasks.md` + `specs/backlog.md`, porque não há código onde comentar. Achado que vira commit é comentado no código.

## Antes de criar

Leia, se existirem:

* `docs/agents/operating-model.md`
* `.specify/memory/project-state.md`
* `.specify/memory/decisions.md`
* `.specify/memory/errors.md`
* `specs/backlog.md`
* `sessoes/index.md`
* specs relacionadas em `specs/`

Se já houver spec relacionada, avise e pergunte antes de duplicar.

## Passos

1. Descobrir o próximo `NNN` sequencial global em `specs/`.
2. **Levantar as decisões de arquitetura/produto** (ver §Regras) — nenhum arquivo é escrito com opção A/B sem escolha registrada.
3. Criar `specs/NNN-<modulo>-<slug>/`.
3. Criar:

   * `spec.md` — inclui **Requisitos numerados (`R1`…`Rn`), testáveis**, Critérios de aceite, Fora de escopo, Riscos e impacto em outros módulos.
   * `plan.md` — inclui Arquitetura da solução, **Arquivos afetados (por módulo/pacote)**, **Contratos/interfaces tocados** (auth/accounts? subdomínio/DNS? schema?), **Impacto em consumidores** (quem mais usa o que vou mexer), Rollback, Validação.
   * `tasks.md`
4. Abrir/atualizar a sessão em `sessoes/` vinculando a spec.
5. Atualizar `project-state.md` **só se** mudar o estado operacional.
4. Abrir ou atualizar sessão em `sessoes/` vinculando a spec.
5. Atualizar `specs/backlog.md` se houver débito ou pendência acionável.
6. Atualizar `project-state.md` se houver mudança operacional.
7. Parar e relatar. Não implementar.

## Conteúdo mínimo

### spec.md

```markdown
# NNN — <título>

- **Módulo/Pacote:** apps/<modulo> | packages/<pkg> | infra
- **Gate relacionado:** A | B | C | D | nenhum
- **Status:** aberto
- **Sessão:** sessoes/<arquivo>.md
- **Decisões de escopo:** o que estiver marcado como decidido **foi de fato decidido pelo
  mantenedor** (com data). Nada aqui é inferência do agente. Achado sem resposta ainda fica
  como pergunta aberta, nunca como decisão fechada.
- **Regra de débito desta spec:** débito/achado descoberto durante a implementação que
  toque o frontend/backend do escopo **é resolvido aqui**, não empurrado pra backlog. O
  agente não decide adiar; na dúvida, pergunta ao mantenedor.
- **Gate de fase:** cada fase de `tasks.md` termina com uma task 🔁 que obriga reler os
  requisitos e seções nomeados deste arquivo e do `plan.md` antes do PR. Divergência:
  corrigir, ou perguntar se a spec é que está errada — nunca seguir o `tasks.md` calado.

## Problema

<Um gap por subseção numerada, cada um com evidência de arquivo:linha ou comando/saída.
Se a versão anterior desta spec (ou outra doc) afirmava algo que o código desmente,
registrar a correção explicitamente — código é a verdade material (`AGENTS.md`).>

## Decisões de escopo tomadas pelo mantenedor (<data>)

### Entra

| Item | Decisão |
|---|---|

### Fica fora (decidido, não esquecido)

| Item | Motivo |
|---|---|

## Requisitos

- **R1:** <requisito testável, com ID citável pela task e pelo gate>

## Critérios de aceite

<Preferir critério objetivamente verificável a julgamento: valor exato em vez de
"não é null"; `git diff` sem caminho proibido; `package.json` sem dependência proibida;
contagem de chamadas em vez de "sem N+1". O que só se checa no olho vira smoke visual
explícito, com quem valida.>

## Fora de escopo

## Riscos e impacto em outros módulos
```

### plan.md

```markdown
# Plano — NNN

Base de fato: toda afirmação sobre estado atual abaixo foi verificada no código (arquivo
e linha citados), não em memória de chat. Rotas e contratos de API vêm da fonte do contrato (OpenAPI ou equivalente, quando existir)
(`AGENTS.md` proíbe usar memória de chat como fonte primária de rota).

## Estado atual verificado (ponto de partida)

| Fato | Onde | Consequência pro plano |
|---|---|---|

<Uma linha por fato que muda a implementação — inclusive os que REDUZEM escopo
("isso já existe, o gap é outro") e as armadilhas ("esse schema descarta campo em
silêncio"). É o que o gate de fase relê.>

## Arquitetura da solução

<Seções com nome estável, para o gate poder citá-las: §"Backend — extração",
§"Frontend", etc. Nome de seção que muda quebra a referência do gate.>

## Arquivos afetados

## Contratos/interfaces tocados

## Impacto em consumidores

## Rollback

<Marcar explicitamente o que NÃO é reversível automaticamente e a mitigação.>

## Validação (como provo que funciona)

<Separar verificação objetiva (comando + resultado esperado) de smoke visual
(quem valida). Smoke visual real é obrigatório antes de fechar task de UI —
`AGENTS.md` proíbe declarar UI pronta sem ver rodando.>
```

### tasks.md

Spec pequena (uma entrega só) usa a forma linear abaixo. Spec com mais de uma frente usa fases, **uma por PR**, cada fase com seu 🔁 gate.

```markdown
# Tasks — NNN

**Modelo de entrega:** <linear | uma fase por PR>. Cada fase fecha sozinha:
código + teste + verde local, PR contra `dev`, bots revisam, achados analisados
na documentação, então a fase seguinte começa.

## 🔁 Gate de fase (obrigatório, penúltima task de TODA fase)

Cada fase termina com uma task **🔁 GATE DE FASE** antes do PR: reler os
requisitos e as seções **nomeados** da `spec.md`/`plan.md` e conferir a
implementação contra eles, item por item. Existe porque `tasks.md` é resumo e
quem implementa tende a ficar preso na checklist.

- Divergência → corrigir antes do PR; se a dúvida é se a spec está errada,
  **perguntar ao mantenedor**.
- **Nunca** seguir o `tasks.md` contra a `spec.md`/`plan.md` em silêncio.
- **Nunca** fechar fase com requisito não atendido nem "atendido em parte".
- Débito descoberto que toca o frontend/backend do escopo **é resolvido nesta
  spec**; o agente não decide adiar — na dúvida, pergunta.

## Pendências técnicas nomeadas (não bloqueiam começar, bloqueiam fechar)

| Onde | O que falta perguntar/decidir |
|---|---|
| T… | <dependência nova a aprovar, forma a escolher, verificação a fazer> |

**Ordem das fases importa:** <dependência real entre fases, se houver>.

---

**Toda fase abre com estas 3 tasks fixas, nesta ordem, antes de qualquer task de conteúdo** — não é boilerplate decorativo, é ordem de execução real:

- [ ] TN.0a — Ler `AGENTS.md` inteiro (T0 pétreo — obrigatório toda sessão/toda fase nova, mesmo se já lido antes nesta mesma sessão) antes de agir nesta fase. · feito quando: leitura confirmada, gate/regra pétrea relevante à fase identificada.
- [ ] TN.0b — Usar `rtk` no lugar de comando cru equivalente durante toda a fase (`rtk git status/diff/log`, `rtk rg`, `rtk read`, `rtk pnpm`, `rtk tsc`, `rtk lint`, `rtk <test-runner>`). · feito quando: nenhum comando cru rodado onde `rtk` cobria o caso.
- [ ] TN.0c — Comunicação com o mantenedor nesta fase em português. · feito quando: mensagens da fase seguem o registro.
- [ ] TN.0d — **Registro anti-compactação contínuo:** todo achado medido nesta fase vai para arquivo **no mesmo turno** — comentário no código se explica o código, bloco da task em `tasks.md` se muda estado/contrato. Obrigatório para: forma óbvia que não funciona (com o sintoma), medição que contradiz o que a spec dizia, valor que varia entre prod e beta, bug latente que falha em silêncio, e decisão de **não** fazer algo. · feito quando: nenhum achado da fase existe só no chat, e `rtk git diff --stat` do `tasks.md` mostra bloco reescrito, não anexado.

## Fase 0 — Decisões de escopo (bloqueante, sem código)

- [ ] T0.1 — <decisão que o mantenedor precisa tomar antes de qualquer código>

## Fase 1 — <nome> · PR próprio

- [ ] T1.1 — <ação concreta> · atende **R<n>** · feito quando <evidência verificável>.
- [ ] T1.2 — Testes: **arquivo novo** `<caminho/Arquivo.test.ts>` | **estendido**
      `<caminho/Existente.test.ts>` — cobrindo <casos, incluindo o de regressão>.
- [ ] T1.3 — 🔁 **GATE DE FASE — cruzar com `spec.md` e `plan.md`.** Reler **R<n>, R<m>**
      e §"<seção>" do `plan.md`; confirmar <2-5 pontos objetivamente verificáveis>.
      Divergência = corrigir ou perguntar, nunca seguir calado.
- [ ] T1.4 — Verde local (`rtk tsc`/lint/test, `pnpm verify:api` se tocar rota) + PR.

## Fase N — Validação final e fechamento

- [ ] TN.0 — 🔁 **GATE FINAL — varredura completa.** Percorrer **todos** os requisitos
      e critérios de aceite um por um, mais os gaps do §Problema, e reconferir as
      travas objetivas — não assumir que os gates de fase cobriram. Requisito não
      atendido = spec não está pronta, mesmo com todas as tasks marcadas.
- [ ] TN.1 — `rtk tsc`/lint/build/test verdes.
- [ ] TN.2 — `pnpm verify:api` final (se tocou `apps/**`, `packages/**`, `scripts/api/**`, `docs/api/openapi/**`).
- [ ] TN.3 — **Auditoria de cobertura de teste**, por tabela: cada arquivo novo/alterado
      com seu `.test` correspondente, separando novos de estendidos, com o caminho de
      cada um. Arquivo tocado sem teste = task reaberta, não fechada.
- [ ] TN.4 — Achados de review de bot resolvidos: o fix que procede vira commit normal
      **com comentário no próprio código** citando origem (PR + bot + severidade), o que
      estava errado e por que a correção é essa — padrão `Achado real (review PR #NNN,
      <bot>, <P1|P2|nitpick>): …` já usado nesta base. O que **não** virou código
      (descartado, ou virou débito) vai pra `tasks.md` + `specs/backlog.md`, com o porquê.
      **Nunca** responder, comentar, resolver thread ou reagir no PR (`AGENTS.md`).
- [ ] TN.5 — Atualizar `specs/backlog.md`, sessão e `project-state.md`. Conferir que
      **nenhuma** pendência da tabela do topo ficou só no chat.
- [ ] TN.6 — Smoke real pós-deploy quando o aceite exigir execução (dry-run/plano/doc
      não fecham task executável — `AGENTS.md` §Erros que não podem se repetir).
```

## Se houver dúvida

Pergunte assim:

```text
Encontrei uma dúvida antes de continuar.

O ponto é: <explicação simples>.

Opções:
1. <opção A>
   Impacto: <impacto>
2. <opção B>
   Impacto: <impacto>

Qual caminho você prefere?
```

## Relatório final

```markdown
# Spec criada

- Caminho: `specs/NNN-<modulo>-<slug>/`
- Arquivos: `spec.md`, `plan.md`, `tasks.md`
- Sessão atualizada: sim/não
- Backlog atualizado: sim/não
- Project-state atualizado: sim/não
- Specs relacionadas encontradas:
- Requisitos com ID (`R1`…`Rn`): <quantos>
- Gate 🔁 em toda fase: sim/não — se não, qual fase ficou sem e por quê
- Gate final (varredura de todos os requisitos) presente: sim/não
- Tabela de cobertura de teste na última fase: sim/não
- Débitos iniciais (linha em `specs/backlog.md`, se houver):
- Pendências técnicas nomeadas (o que ainda falta perguntar ao mantenedor):
``
