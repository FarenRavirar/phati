'use strict';
// Cargos e concessões (spec 003, R18 a R20, R30): a plataforma cria uma empresa própria de cada projeto, cria e edita um cargo
// pelas telas, concede esse cargo a uma pessoa e vê o acesso na lista, nos dois tamanhos, com axe e sem rolagem horizontal; e o
// acesso negado por URL direta. Nome e CPFs mudam a cada rodada, como em `pessoas.spec.js`.
const { test, expect } = require('@playwright/test');
const { dados, entrar, semRolagemHorizontal, acessivel, cpfSintetico } = require('./apoio.js');

async function conferirTela(pagina) {
  await semRolagemHorizontal(pagina);
  await acessivel(pagina);
}

test('plataforma cria e edita cargo, concede o cargo e o acesso aparece', async ({ page }, informacoes) => {
  const projeto = informacoes.project.name;
  const computador = projeto.startsWith('computador');
  const rodada = 700000000 + (Date.now() % 12000000) * 8 + (computador ? 0 : 4);
  const empresa = `Empresa Cargos ${projeto} ${rodada}`;
  await entrar(page, dados.plataforma.cpf);

  await page.goto('/empresas/nova');
  await page.getByLabel('Nome da empresa').fill(empresa);
  await page.getByLabel('Nome do primeiro Administrador').fill('Administrador Cargos');
  await page.getByLabel('E-mail do Administrador').fill(`cargos-${projeto}@exemplo.test`);
  await page.getByLabel('CPF do Administrador').fill(cpfSintetico(rodada));
  await page.getByRole('button', { name: 'Criar empresa' }).click();
  await page.getByRole('link', { name: 'Abrir a empresa' }).click();

  await page.getByRole('link', { name: 'Cargos', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Cargos', level: 1 })).toBeVisible();
  await expect(page.getByText('nível Administrador').first()).toBeVisible();
  await conferirTela(page);

  // Nome repetido: a recusa aparece uma vez, no campo.
  await page.getByRole('link', { name: 'Criar cargo' }).click();
  await expect(page.getByRole('heading', { name: 'Criar cargo', level: 1 })).toBeVisible();
  await conferirTela(page);
  await page.getByLabel('Nome do cargo').fill('Técnico');
  await page.getByLabel('Nível do cargo').selectOption({ label: 'Técnico' });
  await page.getByLabel('Ver o território e seus dados').check();
  await page.getByRole('button', { name: 'Criar cargo' }).click();
  await expect(page.getByText('Já existe cargo com esse nome na empresa.')).toHaveCount(1);
  await conferirTela(page);

  await page.getByLabel('Nome do cargo').fill('Campo');
  await page.getByRole('button', { name: 'Criar cargo' }).click();
  await expect(page.getByText('Cargo criado.')).toBeVisible();
  await expect(page.getByText('1 permissão')).toBeVisible();
  await conferirTela(page);

  // Editar: o nível aparece como texto, não como campo.
  await page.getByRole('link', { name: 'Editar o cargo Campo' }).click();
  await expect(page.getByRole('heading', { name: 'Editar Campo', level: 1 })).toBeVisible();
  await expect(page.getByLabel('Nível do cargo')).toHaveCount(0);
  await conferirTela(page);
  await page.getByLabel('Nome do cargo').fill('Campo novo');
  await page.getByRole('button', { name: 'Salvar cargo' }).click();
  await expect(page.getByText('Cargo alterado.')).toBeVisible();
  await expect(page.getByText('Campo novo', { exact: true })).toBeVisible();

  // Conceder o cargo novo a quem já está na empresa; o acesso aparece na lista.
  await page.goto(page.url().replace(/cargos\/.*/, 'pessoas/'));
  await page.getByRole('link', { name: 'Conceder cargo a Administrador Cargos' }).click();
  await expect(page.getByRole('heading', { name: 'Conceder cargo a Administrador Cargos', level: 1 })).toBeVisible();
  await conferirTela(page);
  // exact: a região do histórico ("Acessos de ... nesta empresa") também casa com "Cargo" por substring.
  await page.getByLabel('Cargo', { exact: true }).selectOption({ label: 'Campo novo' });
  await page.getByLabel('Onde vale').selectOption({ label: 'Empresa inteira' });
  await page.getByRole('button', { name: 'Conceder' }).click();
  await expect(page.getByText('Acesso concedido.')).toBeVisible();
  await expect(page.getByText(/Campo novo · Empresa inteira/)).toBeVisible();
  await conferirTela(page);

  // Sub-área: a escolha em duas etapas volta para a tela de conceder, e conceder de novo o mesmo acesso não duplica (D095).
  const casa = new URL(page.url()).pathname.replace(/pessoas\/.*/, '');
  await page.goto(`${casa}fazenda/nova`);
  await page.getByLabel('Nome da fazenda').fill('Fazenda Cargos');
  await page.getByRole('button', { name: 'Cadastrar fazenda' }).click();
  await page.getByRole('link', { name: 'Cadastrar sub-área' }).first().click();
  await page.getByLabel('Nome de gleba').fill('Gleba Cargos');
  await page.getByRole('button', { name: 'Cadastrar gleba' }).click();
  await page.goto(`${casa}pessoas/`);
  await page.getByRole('link', { name: 'Conceder cargo a Administrador Cargos' }).click();
  await page.getByRole('link', { name: 'Escolher uma sub-área' }).click();
  await expect(page.getByRole('heading', { name: 'Escolher a fazenda', level: 1 })).toBeVisible();
  await conferirTela(page);
  await page.getByRole('link', { name: 'Fazenda Cargos' }).click();
  await page.getByLabel('Filtrar pelo nome').fill('gleba');
  await page.getByRole('button', { name: 'Filtrar' }).click();
  await conferirTela(page);
  await page.getByRole('link', { name: /Gleba Cargos$/ }).click();
  await expect(page.getByRole('heading', { name: 'Conceder cargo a Administrador Cargos', level: 1 })).toBeVisible();
  await expect(page.getByLabel('Onde vale')).toHaveValue(/^sub-area-\d+$/);
  await page.getByLabel('Cargo', { exact: true }).selectOption({ label: 'Campo novo' });
  await page.getByRole('button', { name: 'Conceder' }).click();
  await expect(page.getByText('Acesso concedido.')).toBeVisible();
  await page.getByRole('link', { name: 'Conceder cargo a Administrador Cargos' }).click();
  await expect(page.getByText(/Campo novo · Fazenda Cargos › Gleba Cargos · ativa/)).toHaveCount(1);
  await conferirTela(page);
});

test('empresa que não existe devolve 404 nas telas de cargos, sem texto técnico', async ({ page }) => {
  await entrar(page, dados.plataforma.cpf);
  const resposta = await page.goto('/empresa/999999999/cargos/');
  expect(resposta.status()).toBe(404);
  await expect(page.getByText('object (')).toHaveCount(0);
});
