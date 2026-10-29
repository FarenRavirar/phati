# CLAUDE.md — phati (Claude Code)

@AGENTS.md

O `AGENTS.md` é a fonte canônica de governança e vale integralmente aqui. Este arquivo só
acrescenta o que é específico do Claude Code; nada do `AGENTS.md` se repete aqui.

## Específico do Claude Code

- **Skills:** `.agents/skills/` é a pasta única. Não criar skill em `.claude/skills/`.
- **Hooks ativos** (`.claude/hooks/`): `rtk-enforce` reescreve/bloqueia comando cru;
  `rtk-read-gate` bloqueia leitura integral de arquivo grande; `git-commit-msg-gate`
  bloqueia `-m @'` e `--amend`; `autorizacao-gate` pergunta antes de `commit`, `push`, worktree e
  escrita na VM, mesmo com prefixo `rtk` ou dentro de `bash -lc`, e nega `--amend`, `push --force` e desligar a VM; `caveman-resposta-final` cobra resposta em `ultra`.
- **Permissões** (`.claude/settings.json`): `deny` no que não tem exceção (desligar
  máquina, `--amend`, `push --force`); `ask` no que exige autorização por ação
  (commit, push, merge, worktree, escrita na VM).
- **Navegação:** LSP e `codebase-memory-mcp` antes de busca textual (`AGENTS.md` §Ferramentas).
