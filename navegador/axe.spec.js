'use strict';
// O auditor de verdade (`violacoes`, com as etiquetas e as regras desligadas reais) tem de reprovar defeito de
// acessibilidade: sem isto, uma configuração errada passaria todas as telas em silêncio (achado do Sourcery, PR #22).
const { test, expect } = require('@playwright/test');
const { violacoes } = require('./axe.js');

test('campo sem rótulo é reprovado pelo auditor (regra label)', async ({ page }) => {
  await page.goto('/entrar');
  await page.evaluate(() => {
    const campo = document.createElement('input');
    campo.type = 'text';
    document.querySelector('form').append(campo);
  });
  const regras = (await violacoes(page)).map((violacao) => violacao.regra);
  expect(regras).toContain('label');
});

test('alvo de toque pequeno é reprovado pelo auditor (regra target-size, WCAG 2.2)', async ({ page }) => {
  await page.goto('/entrar');
  const medidas = await page.evaluate(() => {
    // Um alvo pequeno isolado passa (exceção de espaçamento do WCAG 2.5.8); dois colados reprovam.
    // O CSS do produto dá tamanho mínimo a botão nu (24x27 medido), então o tamanho é forçado com !important.
    const alvos = [];
    for (const esquerda of [0, 12]) {
      const botao = document.createElement('button');
      botao.textContent = 'x';
      for (const [propriedade, valor] of [['width', '10px'], ['height', '10px'], ['min-width', '0'], ['min-height', '0'], ['padding', '0'], ['position', 'absolute'], ['top', '0'], ['left', `${esquerda}px`]]) {
        botao.style.setProperty(propriedade, valor, 'important');
      }
      document.body.append(botao);
      alvos.push(botao);
    }
    return alvos.map((botao) => {
      const { width, height } = botao.getBoundingClientRect();
      return { largura: width, altura: height };
    });
  });
  // Controle: sem o tamanho medido abaixo de 24 px o teste não testa nada.
  for (const { largura, altura } of medidas) {
    expect(largura).toBeLessThan(24);
    expect(altura).toBeLessThan(24);
  }
  const regras = (await violacoes(page)).map((violacao) => violacao.regra);
  expect(regras).toContain('target-size');
});

// Página sem servidor (setContent): o axe real roda sobre o HTML dado. Limpa: nenhuma violação.
test('página limpa não tem violação pelo auditor', async ({ page }) => {
  await page.setContent('<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Página limpa</title></head><body><main><h1>Título</h1><p>Texto com contraste de sobra.</p></main></body></html>');
  expect(await violacoes(page)).toEqual([]);
});

// Contraste ruim: o detalhe do nó leva as cores e a razão do axe, para a mensagem do expect mostrar o motivo.
test('texto de contraste ruim é reprovado com cores e razão no detalhe', async ({ page }) => {
  await page.setContent('<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Contraste</title></head><body><main><h1>Título</h1><p style="color:#777;background:#888">texto cinza sobre cinza</p></main></body></html>');
  const contraste = (await violacoes(page)).find((violacao) => violacao.regra === 'color-contrast');
  expect(contraste).toBeDefined();
  expect(contraste.detalhes).toHaveLength(1);
  expect(contraste.detalhes[0]).toMatchObject({ alvo: expect.any(String), fgColor: expect.any(String), bgColor: expect.any(String), contrastRatio: expect.any(Number), expectedContrastRatio: expect.any(String) });
  expect(contraste.detalhes[0].contrastRatio).toBeLessThan(4.5);
});

// Página montada pelo teste (sem servidor), com o CSS da animação: o auditor lê exatamente este HTML e este estilo.
function paginaComEstilo(estilo, corpo) {
  return `<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Animação</title><style>${estilo}</style></head><body><main><h1>Título</h1>${corpo}</main></body></html>`;
}

// Regra da correção: a auditoria espera o fim das animações finitas. Sem a espera, lê a cor no meio do fade-in
// (CI, pessoas.spec.js:64, diálogo do agrion) e reprova texto que já está certo.
test('texto que termina um fade-in longo é auditado depois da animação, não no meio dela', async ({ page }) => {
  await page.setContent(paginaComEstilo('@keyframes surgir { from { opacity: 0.4; } } .surge { animation: surgir 3s linear; }', '<p class="surge">Texto com contraste de sobra.</p>'));
  // Controle: a animação está em curso quando a auditoria começa; sem isto o teste não testa a espera.
  expect(await page.evaluate(() => document.getAnimations().some((animacao) => animacao.playState === 'running'))).toBe(true);
  expect(await violacoes(page)).toEqual([]);
});

// Espera não apaga defeito: com a mesma animação, contraste ruim segue reprovado depois que o fade-in termina.
test('contraste ruim com a mesma animação segue reprovado depois do fim do fade-in', async ({ page }) => {
  await page.setContent(paginaComEstilo('@keyframes surgir { from { opacity: 0.4; } } .surge { animation: surgir 3s linear; color: #777; background: #888; }', '<p class="surge">texto cinza sobre cinza</p>'));
  const regras = (await violacoes(page)).map((violacao) => violacao.regra);
  expect(regras).toContain('color-contrast');
});

// Animação infinita não termina: a espera a deixa de fora, a auditoria roda e a página não trava.
test('animação infinita na página não trava a auditoria', async ({ page }) => {
  await page.setContent(paginaComEstilo('@keyframes girar { to { transform: rotate(360deg); } } .giro { display: inline-block; width: 20px; height: 20px; animation: girar 1s linear infinite; }', '<span class="giro" aria-hidden="true"></span><p>Texto com contraste de sobra.</p>'));
  expect(await violacoes(page)).toEqual([]);
  // Controle: a animação segue em curso depois da auditoria; a espera não a cancelou para liberar a página.
  expect(await page.evaluate(() => document.getAnimations().some((animacao) => animacao.playState === 'running'))).toBe(true);
});

// Animação cancelada durante a espera rejeita `finished`; a rejeição é tratada e a auditoria roda com a página sem ela.
test('animação cancelada durante a espera não derruba a auditoria', async ({ page }) => {
  await page.setContent(paginaComEstilo('', '<p id="texto">Texto com contraste de sobra.</p>'));
  await page.evaluate(() => {
    const animacao = document.getElementById('texto').animate([{ opacity: 0.4 }, { opacity: 1 }], { duration: 3000 });
    setTimeout(() => animacao.cancel(), 300);
  });
  expect(await violacoes(page)).toEqual([]);
});

// Animação que começa quando outra termina também é esperada: a espera refaz a busca até não sobrar animação finita.
// Sem o laço, a auditoria pegaria a segunda no início (opacidade 0.4) logo depois da primeira terminar.
test('animação que começa quando outra termina também é esperada', async ({ page }) => {
  await page.setContent(paginaComEstilo('', '<p id="texto">Texto com contraste de sobra.</p>'));
  await page.evaluate(() => {
    const texto = document.getElementById('texto');
    const primeira = texto.animate([{ opacity: 1 }, { opacity: 1 }], { duration: 300 });
    primeira.finished.then(() => texto.animate([{ opacity: 0.4 }, { opacity: 1 }], { duration: 1000 }));
  });
  expect(await violacoes(page)).toEqual([]);
  // Controle: a segunda animação terminou antes da auditoria devolver o resultado.
  expect(await page.evaluate(() => document.getAnimations().filter((animacao) => animacao.playState !== 'finished').length)).toBe(0);
});

// Animação pausada não termina: a espera a deixa de fora e a página é julgada parada, com opacidade 0.4 (contraste reprovado).
test('animação pausada não trava a auditoria e é julgada no estado em que está', async ({ page }) => {
  await page.setContent(paginaComEstilo('@keyframes surgir { from { opacity: 0.4; } } .surge { animation: surgir 3s linear paused; }', '<p class="surge">Texto com contraste de sobra.</p>'));
  const regras = (await violacoes(page)).map((violacao) => violacao.regra);
  expect(regras).toContain('color-contrast');
});
