#!/usr/bin/env node
// Executa o espelhamento local somente no Windows. Na VM Linux, o backup P: não existe e a sincronização documental
// é responsabilidade do canal remoto definido na spec 010.

const { spawnSync } = require('node:child_process');
const path = require('node:path');

function sincronizar({
  plataforma = process.platform,
  executar = spawnSync,
  script = path.join(__dirname, '..', 'sync-p.ps1'),
} = {}) {
  if (plataforma !== 'win32') return 0;

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
}

if (require.main === module) process.exitCode = sincronizar();

module.exports = { sincronizar };
