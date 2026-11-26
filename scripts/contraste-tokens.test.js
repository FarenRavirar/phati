// A11 (R13): o contraste dos tokens AgriOn passa com os valores finais, e o teste detecta o defeito (borda de campo
// #D8E0D8 sobre a superfície) e o par trocado (texto terciário sobre o nó selecionado, 4,37:1).
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const { analisar, razao, PARES_AGRION } = require('./contraste-tokens.js');

// Cópia byte a byte do pacote AgriOn (conferida por hash em servidor/projeto/testes/test_agrion_copia.py).
const CORES_AGRION = fs.readFileSync(path.join(__dirname, '..', 'servidor', 'projeto', 'static', 'projeto', 'agrion', 'tokens', 'colors.css'), 'utf8');

test('os tokens AgriOn passam, com ao menos um par medido', () => {
  const { erros, pares } = analisar(CORES_AGRION, PARES_AGRION);
  assert.deepEqual(erros, []);
  assert.ok(pares > 0);
});

test('a borda antiga #D8E0D8 reprova o contorno de campo', () => {
  const antigo = CORES_AGRION.replace('--cinza-400: #879089', '--cinza-400: #D8E0D8');
  assert.notEqual(antigo, CORES_AGRION);
  const { erros } = analisar(antigo, PARES_AGRION);
  assert.ok(erros.some((e) => /^--borda-campo sobre --bg-superficie: 1\.\d\d:1, mínimo 3:1$/.test(e)), erros.join('\n'));
});

test('razão de luminância confere com valores conhecidos do WCAG', () => {
  assert.equal(razao('#000000', '#FFFFFF').toFixed(1), '21.0');
  assert.equal(razao('#FFFFFF', '#FFFFFF').toFixed(1), '1.0');
});

test('zero pares reprova', () => {
  assert.ok(analisar(':root { --cor-a: #000000; }').erros.includes('nenhum par de contraste declarado'));
});

test('token fora de par e sem isenção reprova; com isenção e motivo passa', () => {
  const base = ':root { --cor-a: #000000; --cor-b: #FFFFFF; --cor-c: #808080; /* contraste: --cor-a sobre --cor-b >= 4.5 */';
  assert.deepEqual(analisar(`${base} }`).erros, ['--cor-c: fora de qualquer par e sem isenção']);
  assert.deepEqual(analisar(`${base} /* isento: --cor-c (decorativo) */ }`).erros, []);
});

test('isenção sem motivo reprova', () => {
  const css = ':root { --cor-a: #000000; --cor-b: #FFFFFF; /* contraste: --cor-a sobre --cor-b >= 4.5 */ --cor-c: #808080; /* isento: --cor-c () */ }';
  assert.deepEqual(analisar(css).erros, ['--cor-c: isenção sem motivo']);
});

test('par abaixo do mínimo e par com token ausente reprovam', () => {
  const abaixo = ':root { --cor-a: #777777; --cor-b: #888888; /* contraste: --cor-a sobre --cor-b >= 3 */ }';
  assert.match(analisar(abaixo).erros[0], /^--cor-a sobre --cor-b: 1\.\d\d:1, mínimo 3:1$/);
  const ausente = ':root { --cor-a: #000000; /* contraste: --cor-a sobre --cor-z >= 3 */ }';
  assert.match(analisar(ausente).erros[0], /token ausente/);
});

test('token com dígito ou maiúscula também é medido e cobrado', () => {
  const css = ':root { --cor-a: #000000; --cor-b: #FFFFFF; /* contraste: --cor-a sobre --cor-b >= 4.5 */ --cor-cinza-100: #EEEEEE; --cor-Azul2: #123456; }';
  assert.deepEqual(analisar(css).erros, ['--cor-cinza-100: fora de qualquer par e sem isenção', '--cor-Azul2: fora de qualquer par e sem isenção']);
  const abaixo = ':root { --cor-cinza-100: #EEEEEE; --cor-b: #FFFFFF; /* contraste: --cor-cinza-100 sobre --cor-b >= 3 */ }';
  assert.match(analisar(abaixo).erros[0], /^--cor-cinza-100 sobre --cor-b: 1\.\d\d:1, mínimo 3:1$/);
});

test('comentário de contraste malformado reprova em vez de ser ignorado', () => {
  const base = ':root { --cor-a: #000000; --cor-b: #FFFFFF; /* contraste: --cor-a sobre --cor-b >= 4.5 */';
  assert.ok(analisar(`${base} /* contraste: --cor-a sobre --cor-b >= 4..5 */ }`).erros.some((e) => e.includes('fora do formato')));
  assert.ok(analisar(`${base} /* isento: --cor-a motivo sem parênteses */ }`).erros.some((e) => e.includes('fora do formato')));
});

test('declaração de cor dentro de comentário não entra nem substitui a efetiva', () => {
  const par = '/* contraste: --cor-a sobre --cor-b >= 4.5 */';
  // Só existe comentada: o token está ausente para o navegador.
  assert.match(analisar(`:root { --cor-b: #FFFFFF; /* --cor-a: #000000; */ ${par} }`).erros.join(' | '), /token ausente/);
  // Comentada depois da efetiva: não troca a cor medida (#777777 sobre branco falha; #000000 comentada passaria).
  const css = `:root { --cor-a: #777777; --cor-b: #FFFFFF; /* --cor-a: #000000; */ ${par} }`;
  assert.match(analisar(css).erros.join(' | '), /--cor-a sobre --cor-b: 4\.\d\d:1/);
});

test('os tokens AgriOn passam em todos os pares de R13', () => {
  const { erros, pares } = analisar(CORES_AGRION, PARES_AGRION);
  assert.deepEqual(erros, []);
  assert.equal(pares, PARES_AGRION.length);
});

test('texto terciário sobre o hover reprova: a troca única usa o texto secundário', () => {
  const { erros } = analisar(CORES_AGRION, [{ a: '--texto-terciario', b: '--bg-hover', minimo: 4.5 }]);
  assert.deepEqual(erros, ['--texto-terciario sobre --bg-hover: 4.19:1, mínimo 4.5:1']);
});

test('texto terciário sobre o nó selecionado reprova: a troca usa o texto secundário', () => {
  const { erros } = analisar(CORES_AGRION, [{ a: '--texto-terciario', b: '--bg-selecionado', minimo: 4.5 }]);
  assert.deepEqual(erros, ['--texto-terciario sobre --bg-selecionado: 4.37:1, mínimo 4.5:1']);
});

test('o par trocado, texto secundário sobre o nó selecionado, passa (6,24:1)', () => {
  const { erros } = analisar(CORES_AGRION, [{ a: '--texto-secundario', b: '--bg-selecionado', minimo: 4.5 }]);
  assert.deepEqual(erros, []);
});

test('var() resolve em cadeia; referência ausente reprova', () => {
  const css = ':root { --p: var(--c); --c: #777777; --f: #FFFFFF; }';
  assert.match(analisar(css, [{ a: '--p', b: '--f', minimo: 4.5 }]).erros[0], /^--p sobre --f: 4\.4\d:1, mínimo 4\.5:1$/);
  assert.deepEqual(analisar(':root { --p: var(--x); --f: #FFFFFF; }', [{ a: '--p', b: '--f', minimo: 4.5 }]).erros,
    ['--p sobre --f: token ausente ou fora do formato #RRGGBB']);
});

test('ciclo de var() reprova sem travar', () => {
  const css = ':root { --a: var(--b); --b: var(--a); --f: #FFFFFF; }';
  assert.deepEqual(analisar(css, [{ a: '--a', b: '--f', minimo: 3 }]).erros, ['--a sobre --f: token ausente ou fora do formato #RRGGBB']);
});

test('entrada longa sem ponto e vírgula não cresce em tempo quadrático (Sonar S8786)', () => {
  // Regex antiga: ~10 s com 40 mil repetições; a corrigida leva milissegundos. Folga grande para não ser flaky.
  const inicio = Date.now();
  analisar(':root { ' + '--a'.repeat(40000));
  assert.ok(Date.now() - inicio < 1000, `levou ${Date.now() - inicio} ms`);
});

test('valor que não é #RRGGBB não é medido e reprova', () => {
  const css = ':root { --a: rgba(0, 0, 0, 0.5); --f: #FFFFFF; }';
  assert.deepEqual(analisar(css, [{ a: '--a', b: '--f', minimo: 3 }]).erros, ['--a sobre --f: token ausente ou fora do formato #RRGGBB']);
});
