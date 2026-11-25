// Mede o contraste de pares de cor (R13, WCAG 1.4.3 e 1.4.11). Duas fontes de pares:
// (1) comentários `/* contraste: --a sobre --b >= N */` no próprio CSS, quando o CSS traz par (hoje o CSS próprio da AgriOn não traz);
// (2) `PARES_AGRION` deste script, para os tokens AgriOn copiados sem edição (o pacote não recebe anotação).
// `var(--x)` inteiro no valor é resolvido em cadeia; referência ausente ou ciclo reprovam.
// Um token `--cor-*` fora de par só passa com `/* isento: --cor-x (motivo) */`.
// Formato fixo, de espaço simples: regex frouxa tem custo super-linear (Sonar S8786, PR #19) e deixaria passar
// comentário malformado (Qodo e Greptile, PR #19). Nome de token aceita dígito e maiúscula (`--cor-cinza-100`).
const DECLARACAO = /(--[A-Za-z0-9-]+):([^;]+);/g;
const PAR = /\/\* contraste: (--cor-[A-Za-z0-9-]+) sobre (--cor-[A-Za-z0-9-]+) >= (\d+(?:\.\d+)?) \*\//g;
const ISENTO = /\/\* isento: (--cor-[A-Za-z0-9-]+) \(([^)]*)\) \*\//g;
const COMENTARIO_DE_PAR = /\/\*\s*contraste:/g;
const COMENTARIO_DE_ISENCAO = /\/\*\s*isento:/g;
const REFERENCIA = /^var\((--[A-Za-z0-9-]+)\)$/;
const HEX = /^#[0-9a-fA-F]{6}$/;

// Texto 4,5:1 (WCAG AA, 1.4.3); contorno e foco de componente 3:1 (1.4.11). Fonte: specs/012-front-agrion/spec.md R13.
const TEXTOS = ['--texto-primario', '--texto-secundario', '--texto-terciario', '--texto-marca', '--texto-link'];
const FUNDOS = ['--bg-app', '--bg-superficie', '--bg-sutil', '--bg-hover', '--bg-pressionado', '--bg-selecionado'];
const ESTADOS = ['erro', 'aviso', 'info', 'sucesso'];
// Fora da lista, com a medição que justifica: terciário sobre hover (4,19:1) e sobre o nó selecionado (4,37:1), troca única
// da spec R13 (o secundário, 5,99:1 e 6,24:1, entra no lugar pelo CSS próprio `agrion-proprio.css`); terciário sobre
// pressionado (3,78:1), que não aparece: o único uso de `--bg-pressionado` é o botão fantasma `:active` (componentes.css:18),
// com texto secundário.
const SEM_PAR = new Set(['--texto-terciario|--bg-hover', '--texto-terciario|--bg-selecionado', '--texto-terciario|--bg-pressionado']);
const PARES_AGRION = [
  ...TEXTOS.flatMap((a) => FUNDOS.filter((b) => !SEM_PAR.has(`${a}|${b}`)).map((b) => ({ a, b, minimo: 4.5 }))),
  ...ESTADOS.flatMap((e) => [`--${e}-fundo`, '--bg-superficie'].map((b) => ({ a: `--${e}-texto`, b, minimo: 4.5 }))),
  { a: '--texto-inverso', b: '--bg-inverso', minimo: 4.5 },
  { a: '--texto-inverso', b: '--bg-marca', minimo: 4.5 },
  { a: '--sobre-primaria', b: '--acao-primaria', minimo: 4.5 },
  { a: '--sobre-primaria', b: '--acao-primaria-hover', minimo: 4.5 },
  { a: '--sobre-primaria', b: '--acao-primaria-pressionada', minimo: 4.5 },
  ...['--borda-campo', '--borda-foco', '--acao-primaria'].map((a) => ({ a, b: '--bg-superficie', minimo: 3 })),
];

function luminancia(hex) {
  const [r, g, b] = [1, 3, 5].map((i) => Number.parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function razao(a, b) {
  const [claro, escuro] = [luminancia(a), luminancia(b)].sort((x, y) => y - x);
  return (claro + 0.05) / (escuro + 0.05);
}

// Segue `var(--x)` até o valor literal. `visitados` corta ciclo (`--a: var(--b)`, `--b: var(--a)`) sem laço infinito.
function resolver(nome, brutos, visitados = new Set()) {
  if (!brutos.has(nome) || visitados.has(nome)) return undefined;
  visitados.add(nome);
  const valor = brutos.get(nome);
  const referencia = REFERENCIA.exec(valor);
  return referencia ? resolver(referencia[1], brutos, visitados) : valor;
}

function analisar(css, paresExtras = []) {
  const erros = [];
  // Declaração dentro de comentário não vale para o navegador: fora do Map, para não aprovar par com cor que ele não usa
  // (CodeRabbit, PR #19). Os pares e as isenções são comentários e saem do `css` original.
  const semComentarios = css.replace(/\/\*[\s\S]*?\*\//g, '');
  const brutos = new Map([...semComentarios.matchAll(DECLARACAO)].map((m) => [m[1], m[2].trim()]));
  const paresDoCss = [...css.matchAll(PAR)].map((m) => ({ a: m[1], b: m[2], minimo: Number(m[3]) }));
  const pares = [...paresDoCss, ...paresExtras];
  const isentos = new Map([...css.matchAll(ISENTO)].map((m) => [m[1], m[2].trim()]));
  if (pares.length === 0) erros.push('nenhum par de contraste declarado');
  // Comentário que diz `contraste:` ou `isento:` e não casa o formato seria ignorado em silêncio.
  const malformados = (css.match(COMENTARIO_DE_PAR) ?? []).length - paresDoCss.length
    + (css.match(COMENTARIO_DE_ISENCAO) ?? []).length - isentos.size;
  if (malformados > 0) erros.push(`${malformados} comentário(s) de contraste ou isenção fora do formato`);
  const usados = new Set();
  for (const { a, b, minimo } of pares) {
    usados.add(a);
    usados.add(b);
    const cores = [a, b].map((nome) => resolver(nome, brutos));
    if (cores.some((cor) => !HEX.test(cor ?? ''))) {
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
  // A regra de "fora de par" é da convenção `--cor-*`; os tokens AgriOn medem-se só pelos pares.
  for (const nome of brutos.keys()) {
    if (nome.startsWith('--cor-') && !usados.has(nome)) erros.push(`${nome}: fora de qualquer par e sem isenção`);
  }
  return { erros, pares: pares.length };
}

module.exports = { analisar, razao, PARES_AGRION };
