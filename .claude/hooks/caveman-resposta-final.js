#!/usr/bin/env node
// caveman-resposta-final — Stop: lembra o ruleset `caveman ultra` no momento em
// que a resposta final é entregue.
//
// POR QUE EXISTE
// Pedido do mantenedor em 2026-09-21: "crie um hook para te lembrar a cada vez
// que me der uma resposta final, lembrar de usar o caveman ultra".
//
// A cobertura que já existia (hooks globais em `~/.claude/hooks/`) é
// `caveman-activate.js` em `SessionStart` (matchers `startup`, `resume`,
// `clear`, `compact`) e `caveman-mode-tracker.js` em `UserPromptSubmit`. As
// duas chegam ANTES do trabalho. O buraco é o turno longo: entre o
// `UserPromptSubmit` e a resposta final cabem dezenas de chamadas de
// ferramenta, e o ruleset fica longe justamente onde a prosa é escrita.
//
// POR QUE `Stop` E NÃO `PostToolUse`
// Medido na doc oficial (2026-09-21, `code.claude.com/docs/en/hooks`): com
// `exit 0`, "For most events, Claude Code writes stdout to the debug log and
// doesn't show it in the transcript. The exceptions are `UserPromptSubmit`,
// `UserPromptExpansion`, `SessionStart`, and `PostModelSwitch`". `Stop` não
// está entre as exceções, então hook NÃO-bloqueante em `Stop` não alcança o
// modelo — escreve no log e não lembra nada. `PostToolUse` também não está na
// lista, e a própria doc o marca como "Can block? No" em `exit 2`.
//
// Sobra um canal medido: `exit 2` + stderr, que na tabela de `exit 2` da doc
// aparece como `Stop` | "Yes" | "Prevents Claude from stopping, continues the
// conversation". É o mesmo canal que o `registro-anti-compactacao.js` usa neste
// repo, com o raciocínio já registrado lá: `hookSpecificOutput` com
// `hookEventName: "Stop"` NÃO é membro da união e vaza JSON cru para o modelo.
//
// CUSTO ACEITO
// `exit 2` custa um turno extra: a resposta é reescrita no registro certo. O
// mantenedor pediu o lembrete na resposta final, e esse é o único ponto do
// ciclo onde ele chega. Cobrar uma vez por parada é o que impede o laço.
//
// ⚠️ `stop_hook_active` NÃO impede o OUTRO hook `Stop` de cobrar na mesma
// parada. Medido 2026-09-21: este hook e o `registro-anti-compactacao`
// bloquearam juntos, cada um com `exit 2`. A flag corta a REPETIÇÃO do mesmo
// hook depois de uma parada já bloqueada, não a soma de hooks distintos. Por
// isso a mensagem tem teto de 400 chars no teste: com dois cobrando, o que
// limita o custo é o tamanho de cada uma.
//
// COMO ESCAPAR
// Nada a fazer além de responder no registro. A cobrança é UMA por parada:
// `stop_hook_active` corta a segunda, então a resposta reescrita passa direto.

const { lerPayload } = require(require('node:path').join(__dirname, 'ler-payload.js'));

lerPayload((bruto) => {
  // `lerPayload` entrega a string CRUA, não objeto — o parse é de quem chama.
  // Ler `entrada.stop_hook_active` direto do argumento dá `undefined` sempre
  // (propriedade de string), e a trava de laço não existe. Medido: o caso
  // "segunda parada no mesmo turno passa" saiu `exit 2` na 1ª versão.
  let entrada;
  try {
    entrada = JSON.parse(bruto);
  } catch {
    process.exit(0); // não entendeu a entrada: não atrapalha
  }

  // Trava de laço, igual ao hook irmão. O CC marca `stop_hook_active` quando a
  // parada já foi interrompida por hook — sem isto, toda resposta seria
  // bloqueada de novo e a sessão nunca encerraria o turno.
  if (entrada?.stop_hook_active) process.exit(0);

  // Curto de propósito. A mensagem reinjeta a cada parada, e o ruleset completo
  // já chega em `SessionStart` e `UserPromptSubmit` pelos hooks globais. Aqui
  // basta o gatilho: o que cortar, o que nunca cortar, e a saída.
  // Pedido do mantenedor em 2026-10-22: `ponytail` obrigatório, igual ao
  // `caveman`. O nome do hook segue `caveman-resposta-final` para não quebrar o
  // `settings.json`.
  const motivo = [
    '[resposta-final] `caveman ultra` e `ponytail full` são obrigatórios.',
    'caveman: cortar artigo, filler, hedging, preâmbulo, recapitulação;',
    'manter negação, número, unidade, termo técnico, caminho, comando.',
    'ponytail: menor mudança completa; fechar com o que foi pulado e risco.',
    'Prosa normal: aviso de segurança, ação irreversível, texto fora do chat',
    '(código, commit, doc, PR). Já certo? Repetir igual.',
  ].join('\n');

  // Canal: `exit 2` + stderr. Ver o bloco POR QUE `Stop` no cabeçalho — é o
  // único caminho medido que entrega texto ao modelo neste evento.
  // `decision`/`reason` no stdout cobre o caminho síncrono (`claude -p`).
  process.stderr.write(motivo);
  process.stdout.write(JSON.stringify({ decision: 'block', reason: motivo }));
  process.exit(2);
});
