# CLAUDE.md — phati (Claude Code)

@AGENTS.md

O `AGENTS.md` é a fonte canônica de governança e vale integralmente aqui. Este arquivo só
acrescenta o que é específico do Claude Code; nada do `AGENTS.md` se repete aqui.

## Regra pétrea de comunicação com o mantenedor (mandatória, vale acima de tudo abaixo)

O mantenedor trabalha longe do computador e não vê texto parado no terminal. Por isso, **todo
aviso, pendência, decisão ou parada que dependa dele vai em `AskUserQuestion`**, nunca só em
texto de resposta. Sem exceção:

1. **Parou esperando o mantenedor** (aprovação nominal, decisão de produto, autorização,
   "terminei, e agora?", fase fechada, bloqueio): chamar `AskUserQuestion` com 2 a 4 opções,
   a recomendada primeiro, e chamar `PushNotification` (`status: "proactive"`) na mesma vez,
   para o aviso chegar ao celular. A pergunta diz o que está parado e por quê.
2. **Nunca terminar o turno com texto do tipo "aguardo", "fico parado" ou "me chame"** sem a
   pergunta correspondente. Texto assim faz o mantenedor achar que o agente trabalha, quando
   está parado (ocorreu na spec 009).
3. **Trabalho em andamento não vira pergunta**: enquanto há agente ou comando rodando, o
   agente diz isso em uma linha, sem fingir que está bloqueado. Ao terminar o que rodava, se
   restar algo que dependa do mantenedor, aplica a regra 1.
4. **Cada aviso é uma pergunta nova e completa** (autossuficiente: o mantenedor pode ver só o
   diálogo da pergunta). Não reaproveitar aprovação anterior (`AGENTS.md` §Decisão, pausa e
   dúvida).
5. Estado "parado, nada pendente" também é avisado por `AskUserQuestion` (opção "Parar, você
   me chama" incluída), nunca só em texto.

## Específico do Claude Code

- **Skills:** `.agents/skills/` é a pasta única. Não criar skill em `.claude/skills/`.
- **Hooks ativos** (`.claude/hooks/`): `rtk-enforce` reescreve/bloqueia comando cru;
  `rtk-read-gate` bloqueia leitura integral de arquivo grande; `git-commit-msg-gate`
  bloqueia `-m @'` e `--amend`; `branch-gate` nega `git commit` em `dev`/`main`, em branch fora do molde `<tipo>/<escopo>` e em branch já mergeada em `origin/dev` (`PHATI_GATE_BRANCH=0` desliga só essa regra); `autorizacao-gate` pergunta antes de `commit` e de `merge` (`git merge`, `gh pr merge`), mesmo com prefixo `rtk` ou dentro de `bash -lc`/`sh -c`, e nega `--amend`, `push --force` e desligar a VM; `caveman-resposta-final` cobra resposta em `ultra`; `recursos-locais-gate` (`Stop`) bloqueia o fim do turno com contêiner Docker ou `vmmemWSL` de pé; já registrado em `hooks.Stop` de `.claude/settings.json` (a edição desse arquivo está em `allow`, por decisão do mantenedor). `wsl --shutdown` o agente roda ao terminar (`allow` em `.claude/settings.local.json`).
- **Hook `implantacao-gate`** (`PreToolUse` Bash, `.claude/hooks/`): nega a execução direta de `implantar.sh` (com `reverter`/`trocar`), `restaurar.sh` e `backup.sh` na VM, mesmo com `rtk`, `sudo`, `bash -c` ou `ssh`, e manda `gh workflow run implantar --ref main -f sha=<SHA>`; pergunta antes de `trocar-banco.sh`, que não tem workflow.
- **Permissões** (`.claude/settings.json`): `deny` no que não tem exceção (desligar
  máquina, `--amend`, `push --force`); `ask` no que exige autorização por ação
  (commit, merge, `gh pr merge`).
- **Navegação:** LSP antes de busca textual (`AGENTS.md` §Ferramentas).
