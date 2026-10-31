// A11 (R13): o contraste dos tokens passa com os valores finais e o teste detecta o defeito antigo (borda de campo
// #D8E0D8, 1,25:1 sobre o fundo).
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const { analisar, razao } = require('./contraste-tokens.js');

const TOKENS = fs.readFileSync(path.join(__dirname, '..', 'servidor', 'projeto', 'static', 'projeto', 'tokens.css'), 'utf8');

test('os tokens finais passam, com ao menos um par medido', () => {
  const { erros, pares } = analisar(TOKENS);
  assert.deepEqual(erros, []);
  assert.ok(pares > 0);
});

test('a borda antiga #D8E0D8 reprova o contorno de campo', () => {
  const antigo = TOKENS.replace(/(--cor-borda-campo:\s*)#[0-9A-Fa-f]{6}/, '$1#D8E0D8');
  assert.notEqual(antigo, TOKENS);
  const { erros } = analisar(antigo);
  assert.ok(erros.some((e) => e.startsWith('--cor-borda-campo sobre --cor-fundo') && e.includes('1.25:1')), erros.join('\n'));
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
