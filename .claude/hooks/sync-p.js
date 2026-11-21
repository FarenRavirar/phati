#!/usr/bin/env node
// Executa o espelhamento local somente no Windows. Na VM Linux, o backup P: não existe e a sincronização documental
// é responsabilidade do canal remoto definido na spec 010.
//
// Trava: duas sessões que param juntas não rodam `robocopy /MIR` no mesmo P:\phati ao mesmo tempo (as cópias se
// intercalariam). A trava é um arquivo criado com flag `wx` (criação exclusiva: EEXIST se já existe). Quem não pega a
// trava sai 0 com aviso, porque a execução em curso já sincroniza. Trava com mais de TRAVA_MAX_MS é de execução que
// morreu sem liberar: é tomada. Fica em os.tmpdir(), não em P:, para não depender do destino que ela protege.

const fs = require('node:fs');
const os = require('node:os');
const { spawnSync } = require('node:child_process');
const path = require('node:path');

const TRAVA_PADRAO = path.join(os.tmpdir(), 'phati-sync-p.lock');
const TRAVA_MAX_MS = 15 * 60 * 1000;

function criarTrava(arquivo) {
  try {
    fs.writeFileSync(arquivo, String(process.pid), { flag: 'wx' });
    return true;
  } catch (erro) {
    if (erro.code === 'EEXIST') return false;
    throw erro;
  }
}

function adquirirTrava(arquivo, agora = Date.now()) {
  if (criarTrava(arquivo)) return true;
  let idade;
  try {
    idade = agora - fs.statSync(arquivo).mtimeMs;
  } catch {
    return false; // sumiu entre as duas chamadas: outra execução está mexendo nela
  }
  if (idade < TRAVA_MAX_MS) return false;
  fs.rmSync(arquivo, { force: true });
  return criarTrava(arquivo);
}

function sincronizar({
  plataforma = process.platform,
  executar = spawnSync,
  script = path.join(__dirname, '..', 'sync-p.ps1'),
  trava = TRAVA_PADRAO,
} = {}) {
  if (plataforma !== 'win32') return 0;

  let pegou;
  try {
    pegou = adquirirTrava(trava);
  } catch (erro) {
    process.stderr.write(`[sync-p] falha ao criar a trava: ${erro.message}\n`);
    return 1;
  }
  if (!pegou) {
    process.stderr.write('[sync-p] outra sincronização em curso; esta execução não roda.\n');
    return 0;
  }

  try {
    const resultado = executar(
      'powershell',
      ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', script],
      { stdio: 'inherit' },
    );

    if (resultado.error) {
      process.stderr.write(`[sync-p] falha ao iniciar PowerShell: ${resultado.error.message}\n`);
      return 1;
    }
    if (!Number.isInteger(resultado.status)) {
      process.stderr.write('[sync-p] PowerShell terminou sem código de saída.\n');
      return 1;
    }
    return resultado.status;
  } finally {
    fs.rmSync(trava, { force: true });
  }
}

if (require.main === module) process.exitCode = sincronizar();

module.exports = { sincronizar };
