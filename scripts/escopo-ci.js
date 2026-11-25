// Escopo do CI em PR (.github/workflows/ci.yml e codeql.yml, job `escopo`): diz quais jobs e linguagens rodam pelos arquivos alterados.
// Falha fechada: erro do git, lista vazia, base inválida ou arquivo não classificado => tudo roda.
// Push e demais eventos rodam tudo: a promoção para main depende do CI completo no SHA.
const fs = require('node:fs');
const { execFileSync } = require('node:child_process');

const JOBS = ['python', 'node', 'docker', 'navegador'];
const LINGUAGENS = {
  codeql_python: /\.py$/,
  codeql_javascript_typescript: /\.(m?js|cjs|jsx|ts|tsx|html?)$/,
  codeql_actions: /^\.github\//,
};
const CHAVES = [...JOBS, ...Object.keys(LINGUAGENS)];
const BASE_VALIDA = /^[A-Za-z0-9._/-]+$/;

// Primeira regra que casa vence. Lista = jobs que o arquivo aciona.
const REGRAS = [
  [/^\.github\//, JOBS],
  [/^servidor\/.*\.md$/, ['python', 'docker']],
  [/^servidor\/.*\.py$/, ['python', 'docker']],
  // JS de static é lido por pytest (test_paginas, test_pmtiles_terceiros) e por node (mapa.test.js e cia.).
  [/^servidor\/.*\/static\/.*\.js$/, ['python', 'node', 'docker', 'navegador']],
  // Outros arquivos do servidor (compose, nginx, Dockerfile, css, json, html, pmtiles de referência) são lidos por pytest e por testes Node.
  [/^servidor\//, ['python', 'node', 'docker', 'navegador']],
  [/^(navegador\/|playwright\.config\.|package(-lock)?\.json$)/, ['node', 'navegador']],
  [/^(scripts|\.githooks|\.claude)\//, ['node']],
  [/^\.agents\//, []],
  [/\.md$/, []],
];

// null = arquivo não classificado (roda tudo).
function jobsDoArquivo(caminho) {
  for (const [padrao, jobs] of REGRAS) {
    if (padrao.test(caminho)) return jobs;
  }
  return null;
}

function tudo() {
  return Object.fromEntries(CHAVES.map((k) => [k, true]));
}

function classificar({ evento, baseRef, listar }) {
  const nada = () => Object.fromEntries(CHAVES.map((k) => [k, false]));
  if (evento !== 'pull_request') return { ...tudo() };
  if (!baseRef || !BASE_VALIDA.test(baseRef)) return { ...tudo() };
  let arquivos;
  try {
    arquivos = listar(baseRef);
  } catch (error_) {
    process.stderr.write(`escopo-ci: git falhou, rodando tudo: ${error_.message}\n`);
    return { ...tudo() };
  }
  if (arquivos.length === 0) return { ...tudo() };
  const decisao = nada();
  for (const caminho of arquivos) {
    const jobs = jobsDoArquivo(caminho);
    if (jobs === null) return { ...tudo() };
    for (const job of jobs) decisao[job] = true;
    for (const [chave, padrao] of Object.entries(LINGUAGENS)) {
      if (padrao.test(caminho)) decisao[chave] = true;
    }
  }
  return decisao;
}

function decidir(args) {
  return Object.fromEntries(JOBS.map((k) => [k, classificar(args)[k]]));
}

function decidirCodeql(args) {
  const r = classificar(args);
  return Object.fromEntries(Object.keys(LINGUAGENS).map((k) => [k, r[k]]));
}

// `-z` e `--no-renames`: nome com espaço ou quebra de linha sai inteiro, e renomeado conta nos dois lados.
// Caminho fixo: um `git` na frente do PATH não pode ser executado (SonarCloud S4036).
const GIT = '/usr/bin/git';
function listarPadrao(baseRef) {
  const saida = execFileSync(GIT, ['diff', '--name-only', '-z', '--no-renames', `origin/${baseRef}...HEAD`], {
    encoding: 'utf8',
    maxBuffer: 64 * 1024 * 1024,
  });
  return saida.split('\0').filter(Boolean);
}

function principal() {
  const decisao = classificar({
    evento: process.env.GITHUB_EVENT_NAME ?? '',
    baseRef: process.env.GITHUB_BASE_REF ?? '',
    listar: listarPadrao,
  });
  const linhas = CHAVES.map((k) => `${k}=${decisao[k]}\n`).join('');
  if (process.env.GITHUB_OUTPUT) fs.appendFileSync(process.env.GITHUB_OUTPUT, linhas);
  else process.stdout.write(linhas);
}

if (require.main === module) principal();

module.exports = { decidir, decidirCodeql, jobsDoArquivo, listarPadrao };
