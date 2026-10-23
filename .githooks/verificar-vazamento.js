#!/usr/bin/env node
'use strict';
// Barreira de pré-commit contra vazamento num repositório PÚBLICO.
//
// Bloqueia o commit quando o conteúdo em stage tem: arquivo sensível (segredo,
// dado geoespacial, documento do cliente, dump), segredo no texto (chave
// privada, token, senha atribuída, string de conexão com senha), IP público ou
// termo da lista local `.githooks/termos-sensiveis.local`.
//
// Decisões:
// - A lista de termos (nomes de cliente, fazenda, pessoa) fica FORA do
//   repositório: versioná-la vazaria justamente o que ela protege.
// - A mensagem nunca repete o valor encontrado, só arquivo, linha e regra.
// - Sem escape (`--no-verify` é barrado em `.claude/settings.json`). Falso
//   positivo se resolve mudando o dado ou a regra, com teste.
// - Falha ao ler o git bloqueia o commit (falha fechada).

const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

const ARQUIVO_TERMOS = path.join('.githooks', 'termos-sensiveis.local');

const REGRAS_CAMINHO = [
  { regra: 'arquivo de segredo', teste: /(^|\/)\.env(\.[^/]*)?$/i, exceto: /\.(example|exemplo)$/i },
  { regra: 'chave ou certificado', teste: /\.(key|pem|p12|pfx|jks|keystore|ppk)$/i },
  { regra: 'chave SSH', teste: /(^|\/)id_(rsa|dsa|ecdsa|ed25519)$/ },
  { regra: 'dado geoespacial', teste: /\.(tiff?|shp|shx|dbf|prj|gpkg|kml|kmz|mbtiles|pmtiles|las|laz|ecw|jp2)$/i },
  { regra: 'banco ou dump local', teste: /\.(dump|bak|sqlite3?|db)$/i },
  { regra: 'dump compactado', teste: /\.sql\.gz$/i },
  { regra: 'documento do cliente', teste: /\.(pdf|docx?|xlsx?|pptx?)$/i },
  // Qualquer `DEFINI*.md` (definição funcional do cliente). O padrão antigo exigia
  // "FUNCIONAL" no nome e deixou `DEFINICAO.md` passar quando o arquivo foi renomeado.
  { regra: 'documento de definição do cliente', teste: /(^|\/)DEFINI[^/]*\.md$/i },
  { regra: 'arquivo local', teste: /(^|\/)[^/]*\.local(\.[^/]*)?$/i },
  { regra: 'pasta de dados ou segredos', teste: /^(dados|insumos|clientes|privado|segredos)\//i },
];

const REGRAS_CONTEUDO = [
  { regra: 'chave privada', teste: /-----BEGIN [A-Z ]*PRIVATE KEY-----/ },
  { regra: 'token do GitHub', teste: /\bgh[pousr]_[A-Za-z0-9]{30,}\b/ },
  { regra: 'token do GitHub (fino)', teste: /\bgithub_pat_[A-Za-z0-9_]{30,}\b/ },
  { regra: 'chave AWS', teste: /\b(AKIA|ASIA)[0-9A-Z]{16}\b/ },
  { regra: 'token Slack', teste: /\bxox[abprs]-[A-Za-z0-9-]{10,}/ },
  { regra: 'chave de API (sk-)', teste: /\bsk-[A-Za-z0-9_-]{20,}\b/ },
  { regra: 'JWT', teste: /\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}/ },
  {
    regra: 'senha ou segredo atribuído',
    teste: /\b(senha|password|passwd|secret|segredo|token|api[_-]?key|chave[_-]?api)\w*\s*[:=]\s*['"][^'"\s]{8,}['"]/i,
  },
  { regra: 'string de conexão com senha', teste: /\b[a-z][a-z0-9+.-]*:\/\/[^\s:@/]+:[^\s@/]+@[^\s/]+/i },
];

const REGEX_IPV4 = /(?<![\w.])(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?![\w.]*\d)/g;

function ipv4Publico(octetos) {
  const [a, b, c] = octetos;
  if (octetos.some((n) => n > 255)) return false;
  if (a === 0 || a === 10 || a === 127 || a >= 224) return false;
  if (a === 169 && b === 254) return false;
  if (a === 172 && b >= 16 && b <= 31) return false;
  if (a === 192 && b === 168) return false;
  if (a === 100 && b >= 64 && b <= 127) return false;
  if (a === 192 && b === 0 && c === 2) return false;
  if (a === 198 && b === 51 && c === 100) return false;
  if (a === 203 && b === 0 && c === 113) return false;
  return true;
}

function normalizar(texto) {
  return texto.normalize('NFD').replace(/\p{M}/gu, '').toLowerCase();
}

// Nome de arquivo troca espaço por hífen, sublinhado ou ponto; sem isto o termo
// "fazenda modelo" nunca casaria com `relatorio-fazenda-modelo.md`.
function normalizarNome(caminho) {
  return normalizar(caminho).replace(/[\s._/-]+/g, ' ');
}

function ehBinario(buffer) {
  return buffer.subarray(0, 8000).includes(0);
}

function verificarCaminho(caminho) {
  const normal = caminho.replace(/\\/g, '/');
  return REGRAS_CAMINHO.filter((r) => r.teste.test(normal) && !(r.exceto && r.exceto.test(normal))).map((r) => ({
    arquivo: caminho,
    linha: 0,
    regra: r.regra,
  }));
}

function verificarConteudo(caminho, texto, termos) {
  const achados = [];
  const termosNormalizados = termos.map(normalizar).filter(Boolean);
  texto.split(/\r?\n/).forEach((linha, indice) => {
    const numero = indice + 1;
    for (const r of REGRAS_CONTEUDO) {
      if (r.teste.test(linha)) achados.push({ arquivo: caminho, linha: numero, regra: r.regra });
    }
    for (const m of linha.matchAll(REGEX_IPV4)) {
      if (ipv4Publico(m.slice(1, 5).map(Number))) {
        achados.push({ arquivo: caminho, linha: numero, regra: 'endereço IP público' });
      }
    }
    const linhaNormalizada = normalizar(linha);
    if (termosNormalizados.some((t) => linhaNormalizada.includes(t))) {
      achados.push({ arquivo: caminho, linha: numero, regra: 'termo da lista sensível local' });
    }
  });
  return achados;
}

// Núcleo puro: recebe os caminhos em stage e uma função que devolve o Buffer de
// cada um. Não toca no git nem no disco, para ser testável.
function verificar({ caminhos, lerConteudo, termos = [] }) {
  const achados = [];
  for (const caminho of caminhos) {
    achados.push(...verificarCaminho(caminho));
    const nomeNormalizado = normalizarNome(caminho);
    const termoNoNome = termos.map(normalizarNome).filter(Boolean).some((t) => nomeNormalizado.includes(t));
    if (termoNoNome) achados.push({ arquivo: caminho, linha: 0, regra: 'termo da lista sensível local no nome' });
    const buffer = lerConteudo(caminho);
    if (!buffer || ehBinario(buffer)) continue;
    achados.push(...verificarConteudo(caminho, buffer.toString('utf8'), termos));
  }
  return achados;
}

function lerTermos(raiz) {
  const arquivo = path.join(raiz, ARQUIVO_TERMOS);
  if (!fs.existsSync(arquivo)) return [];
  return fs
    .readFileSync(arquivo, 'utf8')
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter((l) => l && !l.startsWith('#'));
}

function git(args, opcoes = {}) {
  return execFileSync('git', args, { maxBuffer: 256 * 1024 * 1024, ...opcoes });
}

function principal() {
  const raiz = git(['rev-parse', '--show-toplevel'], { encoding: 'utf8' }).trim();
  const saida = git(['diff', '--cached', '--name-only', '--diff-filter=ACMR', '-z'], { cwd: raiz, encoding: 'utf8' });
  const caminhos = saida.split('\0').filter(Boolean);
  const achados = verificar({
    caminhos,
    lerConteudo: (c) => git(['show', `:${c}`], { cwd: raiz }),
    termos: lerTermos(raiz),
  });
  if (achados.length === 0) return 0;
  process.stderr.write('COMMIT BLOQUEADO: possível vazamento em repositório público.\n');
  for (const a of achados) {
    process.stderr.write(`  ${a.arquivo}${a.linha ? `:${a.linha}` : ''} — ${a.regra}\n`);
  }
  process.stderr.write('Remova o dado do stage (git restore --staged <arquivo>). O valor não é exibido de propósito.\n');
  return 1;
}

if (require.main === module) {
  try {
    process.exit(principal());
  } catch (erro) {
    process.stderr.write(`COMMIT BLOQUEADO: a verificação falhou (${erro.message}).\n`);
    process.exit(1);
  }
}

module.exports = { verificar, verificarCaminho, verificarConteudo, ipv4Publico };
