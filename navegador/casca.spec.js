'use strict';
// Casca autenticada (spec 012, R11 e R15 a R17; telas.md §0): sem rolagem horizontal, gaveta e foco, seletor de escopo,
// menu sem JS, logo, alvos de 44 px em 320, CSP limpa no console e acesso negado por URL direta.
// As capturas vão para PHATI_CAPTURAS_DIR, quando definido (o nome traz o projeto, ou seja, o tamanho da tela).
// Sem `test.skip`: quando a regra só vale numa largura, o teste confere a largura e segue pelo ramo da outra.
const path = require('node:path');
const { test, expect } = require('@playwright/test');
const { dados, entrar, semRolagemHorizontal, acessivel, caberNoBotao, TEXTO_LONGO } = require('./apoio.js');

const TELAS = [
  ['inicio', '/'],
  ['fazendas', '/empresa/1/'],
  ['pessoas', '/empresa/1/pessoas/'],
  ['cargos', '/empresa/1/cargos/'],
  ['fazenda', '/empresa/1/fazenda/1/'],
];

// A casca passa a ter gaveta abaixo de 64 rem (1024 px); a largura de 1280 px é o computador.
const LARGURA_COMPUTADOR = 1280;
const estreita = (pagina) => pagina.viewportSize().width < LARGURA_COMPUTADOR;

async function capturar(pagina, nome) {
  if (!process.env.PHATI_CAPTURAS_DIR) return;
  await pagina.screenshot({ path: path.join(process.env.PHATI_CAPTURAS_DIR, `casca-${nome}-${test.info().project.name}.png`) });
}

async function abrirGaveta(pagina) {
  await pagina.locator('[data-abrir-menu]').click();
  await expect(pagina.locator('.ag-casca')).toHaveAttribute('data-gaveta', '');
  // A gaveta desliza (transform, --duracao-media): a posição só se lê depois que ela para.
  await expect.poll(() => pagina.locator('.ag-sidebar').evaluate((e) => e.getBoundingClientRect().left)).toBe(0);
}

for (const [nome, rota] of TELAS) {
  test(`sem rolagem horizontal, com axe e alvos da casca em ${nome}`, async ({ page }) => {
    await entrar(page, dados.administradora_a.cpf);
    await page.goto(rota);
    await expect(page.locator('.ag-conteudo')).toBeVisible();
    await semRolagemHorizontal(page);
    await acessivel(page);
    await capturar(page, nome);
  });
}

// Telas públicas (sem casca): centralizadas em 320 e 1280, sem rolagem horizontal; a captura confere o rodapé de termos.
for (const [nome, rota] of [['entrar', '/entrar'], ['esqueci-senha', '/esqueci-senha']]) {
  test(`tela pública ${nome} centralizada, sem rolagem horizontal e capturada`, async ({ page }) => {
    await page.goto(rota);
    await expect(page.locator('.ag-publica')).toBeVisible();
    await semRolagemHorizontal(page);
    await capturar(page, nome);
  });
}

test('logo horizontal tem 95×26 px (R15)', async ({ page }) => {
  await entrar(page, dados.administradora_a.cpf);
  await page.goto('/');
  const logo = page.locator('.ag-sidebar-marca img[alt="AgriOn"]');
  const caixa = await logo.boundingBox();
  expect(caixa.width).toBeCloseTo(95, 0);
  expect(caixa.height).toBeCloseTo(26, 0);
});

test('gaveta aberta em 320 ocupa 280 px desde a borda esquerda (R15); no computador não há gaveta', async ({ page }) => {
  await entrar(page, dados.administradora_a.cpf);
  await page.goto('/');
  if (!estreita(page)) {
    await expect(page.locator('[data-abrir-menu]')).toBeHidden();
    return;
  }
  await abrirGaveta(page);
  const caixa = await page.locator('.ag-sidebar').boundingBox();
  expect(caixa.x, 'gaveta aberta não encosta na borda esquerda').toBeCloseTo(0, 0);
  expect(caixa.width, 'largura da gaveta aberta').toBeCloseTo(280, 0);
});

test('título do grupo sem margem e item atual com a altura do pacote (R12, regressão do base.css próprio)', async ({ page }) => {
  await entrar(page, dados.administradora_a.cpf);
  await page.goto('/');
  // Altura do pacote (agrion/styles/casca.css): .ag-nav-item 34 px; 44 px abaixo de 64rem (o próprio agrion-proprio.css).
  const altura = estreita(page) ? 44 : 34;
  const titulo = await page.locator('.ag-nav-titulo').first().evaluate((e) => getComputedStyle(e).marginBottom);
  expect(titulo, 'margem de baixo do título do grupo').toBe('0px');
  const item = await page.locator('.ag-nav-item[aria-current]').first().boundingBox();
  expect(item.height, 'altura do item atual').toBeCloseTo(altura, 0);
});

test('botões Fixar, Ocultar e Mostrar do Início usam o estilo da casca (regressão: saíam nativos)', async ({ page }) => {
  await entrar(page, dados.administradora_a.cpf);
  await page.goto('/');
  const botoes = page.locator('.controles-atalho button');
  await expect(botoes.first()).toBeVisible();
  const sem = await botoes.evaluateAll((els) => els.filter((e) => !e.classList.contains('ag-botao')).map((e) => e.textContent.trim()));
  expect(sem, 'botões de atalho sem ag-botao').toEqual([]);
});

test('o botão Menu aponta a um elemento que existe (WCAG 4.1.2, regressão do aria-controls)', async ({ page }) => {
  await entrar(page, dados.administradora_a.cpf);
  await page.goto('/');
  const alvo = await page.locator('[data-abrir-menu]').getAttribute('aria-controls');
  expect(alvo, 'botão Menu sem aria-controls').toBeTruthy();
  await expect(page.locator(`[id="${alvo}"]`)).toHaveCount(1);
});

test('alvos da casca têm 44 px ou mais em 320 (R11); no computador não há gaveta', async ({ page }) => {
  await entrar(page, dados.administradora_a.cpf);
  await page.goto('/');
  if (!estreita(page)) {
    await expect(page.locator('[data-abrir-menu]')).toBeHidden();
    return;
  }
  await abrirGaveta(page);
  const alvos = await page.locator('.ag-nav-item, [data-escopo-abrir], [data-abrir-menu], form[action="/sair"] button').evaluateAll((elementos) =>
    elementos.filter((e) => e.offsetParent !== null).map((e) => {
      const r = e.getBoundingClientRect();
      return { texto: e.textContent.trim().slice(0, 30), largura: r.width, altura: r.height };
    }),
  );
  expect(alvos.length, 'nenhum alvo visível na gaveta').toBeGreaterThan(0);
  expect(alvos.filter((a) => a.largura < 44 || a.altura < 44)).toEqual([]);
});

test('gaveta abre pelo botão, leva o foco ao menu e fecha ao escolher um item; no computador o botão não existe', async ({ page }) => {
  await entrar(page, dados.administradora_a.cpf);
  await page.goto('/');
  if (!estreita(page)) {
    await expect(page.locator('[data-abrir-menu]')).toBeHidden();
    return;
  }
  await abrirGaveta(page);
  await expect(page.locator('.ag-nav-principal a').first()).toBeFocused();
  await page.locator('.ag-sidebar a', { hasText: 'Pessoas' }).click();
  await expect(page).toHaveURL(/\/empresa\/1\/pessoas\/$/);
  await expect(page.locator('.ag-casca')).not.toHaveAttribute('data-gaveta', '');
});

test('fundo da gaveta fecha e devolve o foco ao botão (R15); no computador o botão não existe', async ({ page }) => {
  await entrar(page, dados.administradora_a.cpf);
  await page.goto('/');
  if (!estreita(page)) {
    await expect(page.locator('[data-abrir-menu]')).toBeHidden();
    return;
  }
  await abrirGaveta(page);
  await page.mouse.click(300, 300);
  await expect(page.locator('.ag-casca')).not.toHaveAttribute('data-gaveta', '');
  await expect(page.locator('[data-abrir-menu]')).toBeFocused();
});

test('Esc fecha a gaveta e devolve o foco ao botão (R15); no computador o botão não existe', async ({ page }) => {
  await entrar(page, dados.administradora_a.cpf);
  await page.goto('/');
  if (!estreita(page)) {
    await expect(page.locator('[data-abrir-menu]')).toBeHidden();
    return;
  }
  await abrirGaveta(page);
  await page.keyboard.press('Escape');
  await expect(page.locator('.ag-casca')).not.toHaveAttribute('data-gaveta', '');
  await expect(page.locator('[data-abrir-menu]')).toBeFocused();
});

test('gaveta fechada não recebe foco por Tab em 320 (R11, caminho infeliz); no computador não há gaveta', async ({ page }) => {
  await entrar(page, dados.administradora_a.cpf);
  await page.goto('/');
  if (!estreita(page)) {
    await expect(page.locator('[data-abrir-menu]')).toBeHidden();
    return;
  }
  const alcancados = [];
  for (let i = 0; i < 40; i += 1) {
    await page.keyboard.press('Tab');
    alcancados.push(await page.evaluate(() => {
      const el = document.activeElement;
      return el && el.closest('.ag-sidebar') ? (el.textContent.trim() || el.getAttribute('aria-label')) : null;
    }));
  }
  expect(alcancados.filter(Boolean), 'o Tab entrou na gaveta fechada').toEqual([]);
});

test('seletor troca a empresa e a casca passa a mostrá-la (R17)', async ({ page }) => {
  await entrar(page, dados.plataforma.cpf);
  await page.goto('/');
  if (estreita(page)) await abrirGaveta(page);
  await page.locator('[data-escopo-abrir]').click();
  await expect(page.locator('#escopo-lista')).toBeVisible();
  await page.locator('#escopo-lista button', { hasText: 'Empresa Inventada B' }).click();
  await expect(page.locator('.ag-escopo-texto b')).toHaveText('Empresa Inventada B');
});

test('escolher empresa B estando em uma tela da empresa A leva a / com B escolhida (R17)', async ({ page }) => {
  await entrar(page, dados.plataforma.cpf);
  await page.goto('/empresa/1/pessoas/');
  if (estreita(page)) await abrirGaveta(page);
  await page.locator('[data-escopo-abrir]').click();
  await expect(page.locator('#escopo-lista')).toBeVisible();
  await page.locator('#escopo-lista button', { hasText: 'Empresa Inventada B' }).click();
  await expect(page).toHaveURL((url) => url.pathname === '/');
  await expect(page.locator('.ag-escopo-texto b')).toHaveText('Empresa Inventada B');
});

test('lista do seletor com muitos itens rola dentro da janela e o último item alcança (R11, R15, regressão)', async ({ page }) => {
  await entrar(page, dados.administradora_a.cpf);
  await page.goto('/');
  if (estreita(page)) await abrirGaveta(page);
  const lista = page.locator('#escopo-lista');
  // Itens sintéticos entram antes do link fixo Empresas: o último da lista é o fixo, como no caso de 15 fazendas.
  await lista.evaluate((l) => {
    const fixo = l.querySelector('a[href="/empresas/"]');
    for (let i = 1; i <= 15; i += 1) {
      const item = document.createElement('a');
      item.className = 'ag-botao';
      item.dataset.variante = 'fantasma';
      item.dataset.tamanho = 'sm';
      item.href = '#';
      item.textContent = `Fazenda Inventada ${i}`;
      l.insertBefore(item, fixo);
    }
  });
  await page.locator('[data-escopo-abrir]').click();
  await expect(lista).toBeVisible();
  const ultimo = lista.locator('a').last();
  await ultimo.evaluate((a) => a.scrollIntoView({ block: 'end' }));
  const rolagem = await lista.evaluate((l) => ({ rolavel: l.scrollHeight > l.clientHeight, rolou: l.scrollTop > 0 }));
  expect(rolagem.rolavel, 'lista do seletor sem altura útil menor que o conteúdo').toBe(true);
  expect(rolagem.rolou, 'a própria lista não rolou até o último item').toBe(true);
  const janela = await page.evaluate(() => window.innerHeight);
  const caixaLista = await lista.boundingBox();
  const caixaUltimo = await ultimo.boundingBox();
  expect(caixaLista.y + caixaLista.height, 'lista do seletor passa da janela').toBeLessThanOrEqual(janela);
  expect(caixaUltimo.y + caixaUltimo.height, 'último item do seletor fica abaixo da janela').toBeLessThanOrEqual(janela);
});

test('escolher empresa sem acesso é recusada com 404 e não vira escolhida (R17, R16, caminho infeliz)', async ({ page }) => {
  await entrar(page, dados.administradora_a.cpf);
  await page.goto('/');
  const antes = await page.locator('.ag-escopo-texto b').textContent();
  // POST direto, com o CSRF da própria página: o seletor só mostra empresas alcançadas, então a recusa é do servidor.
  const status = await page.evaluate(async (empresa) => {
    const token = document.querySelector('input[name=csrfmiddlewaretoken]').value;
    const corpo = new URLSearchParams({ escolhida: String(empresa), proximo: '/', csrfmiddlewaretoken: token });
    const resposta = await fetch('/escolher-empresa', { method: 'POST', body: corpo, credentials: 'same-origin', redirect: 'manual' });
    return resposta.status;
  }, dados.empresa_b);
  expect(status, 'empresa sem acesso foi aceita').toBe(404);
  await page.goto('/');
  await expect(page.locator('.ag-escopo-texto b')).toHaveText(antes);
  await expect(page.locator('.ag-escopo-texto b')).not.toHaveText('Empresa Inventada B');
});

test.describe('sem JavaScript', () => {
  test.use({ javaScriptEnabled: false });

  test('o menu sem JS: em 320 abre e fecha pelo <details> (R15); em 1280 aparece inteiro (R15)', async ({ page }) => {
    await entrar(page, dados.administradora_a.cpf);
    await page.goto('/');
    const itemPessoas = page.locator('.ag-sidebar .ag-nav-item', { hasText: 'Pessoas' });
    if (!estreita(page)) {
      await expect(page.locator('.ag-sidebar .ag-nav-item', { hasText: 'Início' })).toBeVisible();
      return;
    }
    await expect(itemPessoas).toBeVisible();
    await page.locator('.ag-sidebar-resumo').click();
    await expect(itemPessoas).toBeHidden();
    await page.locator('.ag-sidebar-resumo').click();
    await expect(itemPessoas).toBeVisible();
  });
});

test('sem violação de CSP no console das telas da casca (R15)', async ({ page }) => {
  const violacoes = [];
  page.on('console', (mensagem) => {
    if (/content security policy|content-security-policy/i.test(mensagem.text())) violacoes.push(mensagem.text());
  });
  page.on('pageerror', (erro) => violacoes.push(erro.message));
  await entrar(page, dados.administradora_a.cpf);
  for (const [, rota] of TELAS) {
    await page.goto(rota);
    await expect(page.locator('.ag-conteudo')).toBeVisible();
  }
  expect(violacoes).toEqual([]);
});

test('acesso negado por URL direta à casca de quem não tem alcance (R16, caminho infeliz)', async ({ page }) => {
  await entrar(page, dados.sem_acesso.cpf);
  for (const rota of ['/empresa/1/pessoas/', '/empresa/1/cargos/', '/empresa/1/fazenda/1/']) {
    const resposta = await page.goto(rota);
    expect(resposta.status(), `status de ${rota}`).toBe(404);
    await expect(page.locator('.ag-sidebar .ag-nav-item', { hasText: 'Pessoas' })).toHaveCount(0);
  }
});

test('botões da casca com texto de dado longo quebram sem rolagem horizontal (regressão, nowrap do pacote)', async ({ page }) => {
  await entrar(page, dados.administradora_a.cpf);
  await page.goto('/');
  // Atalho do Início: o nome vem de dado, então o rótulo "Ocultar X" cresce com ele.
  const atalho = page.locator('.controles-atalho button').first();
  await expect(atalho).toBeVisible();
  await atalho.evaluate((b, t) => { b.textContent = t; }, `Ocultar ${TEXTO_LONGO}`);
  const medidaAtalho = await caberNoBotao(atalho);
  expect(medidaAtalho.altura, 'atalho com texto longo não fica abaixo do mínimo do alvo').toBeGreaterThanOrEqual(medidaAtalho.minimo);
  // Seletor de escopo: a lista nasce com `hidden` e abre ao tirá-lo (o que casca.js faz no clique); o item recebe o nome longo.
  const lista = page.locator('[data-escopo-lista]');
  await lista.evaluate((l, t) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'ag-botao';
    b.dataset.variante = 'fantasma';
    b.dataset.tamanho = 'sm';
    b.dataset.testeLongo = '';
    b.textContent = t;
    l.append(b);
    l.hidden = false;
  }, TEXTO_LONGO);
  const escopo = page.locator('[data-teste-longo]');
  await caberNoBotao(escopo);
  const caixa = await escopo.boundingBox();
  const caixaLista = await lista.boundingBox();
  expect(caixa.width, 'item do seletor de escopo passa da largura da lista').toBeLessThanOrEqual(caixaLista.width + 0.5);
  await semRolagemHorizontal(page);
});
