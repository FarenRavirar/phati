// Mede o contraste dos pares declarados em tokens.css por comentários `/* contraste: --a sobre --b >= N */` (R13, WCAG
// 1.4.3 e 1.4.11). Um token `--cor-*` fora de par só passa com `/* isento: --cor-x (motivo) */`.
// Formato fixo, de espaço simples: regex frouxa tem custo super-linear (Sonar S8786, PR #19) e deixaria passar
// comentário malformado (Qodo e Greptile, PR #19). Nome de token aceita dígito e maiúscula (`--cor-cinza-100`).
const TOKEN = /(--cor-[A-Za-z0-9-]+):([^;]+);/g;
const PAR = /\/\* contraste: (--cor-[A-Za-z0-9-]+) sobre (--cor-[A-Za-z0-9-]+) >= (\d+(?:\.\d+)?) \*\//g;
const ISENTO = /\/\* isento: (--cor-[A-Za-z0-9-]+) \(([^)]*)\) \*\//g;
const COMENTARIO_DE_PAR = /\/\*\s*contraste:/g;
const COMENTARIO_DE_ISENCAO = /\/\*\s*isento:/g;

function luminancia(hex) {
  const [r, g, b] = [1, 3, 5].map((i) => Number.parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function razao(a, b) {
  const [claro, escuro] = [luminancia(a), luminancia(b)].sort((x, y) => y - x);
  return (claro + 0.05) / (escuro + 0.05);
}

function analisar(css) {
  const erros = [];
  const tokens = new Map([...css.matchAll(TOKEN)].map((m) => [m[1], m[2].trim()]));
  const pares = [...css.matchAll(PAR)].map((m) => ({ a: m[1], b: m[2], minimo: Number(m[3]) }));
  const isentos = new Map([...css.matchAll(ISENTO)].map((m) => [m[1], m[2].trim()]));
  if (pares.length === 0) erros.push('nenhum par de contraste declarado');
  // Comentário que diz `contraste:` ou `isento:` e não casa o formato seria ignorado em silêncio.
  const malformados = (css.match(COMENTARIO_DE_PAR) ?? []).length - pares.length
    + (css.match(COMENTARIO_DE_ISENCAO) ?? []).length - isentos.size;
  if (malformados > 0) erros.push(`${malformados} comentário(s) de contraste ou isenção fora do formato`);
  const usados = new Set();
  for (const { a, b, minimo } of pares) {
    usados.add(a);
    usados.add(b);
    const cores = [a, b].map((nome) => tokens.get(nome));
    if (cores.some((cor) => !/^#[0-9a-fA-F]{6}$/.test(cor ?? ''))) {
      erros.push(`${a} sobre ${b}: token ausente ou fora do formato #RRGGBB`);
      continue;
    }
    const medida = razao(...cores);
    if (medida < minimo) erros.push(`${a} sobre ${b}: ${medida.toFixed(2)}:1, mínimo ${minimo}:1`);
  }
  for (const [nome, motivo] of isentos) {
    if (!motivo) erros.push(`${nome}: isenção sem motivo`);
    usados.add(nome);
  }
  for (const nome of tokens.keys()) {
    if (!usados.has(nome)) erros.push(`${nome}: fora de qualquer par e sem isenção`);
  }
  return { erros, pares: pares.length };
}

module.exports = { analisar, razao };
