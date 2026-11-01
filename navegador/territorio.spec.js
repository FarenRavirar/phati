'use strict';
// Gestão do território (spec 003, R9 a R12, R30): criar, renomear, arquivar e desarquivar pelas telas, nos dois tamanhos,
// com axe e sem rolagem horizontal; e o acesso negado por URL direta. O Administrador da plataforma cria uma empresa
// própria de cada projeto e muda só ela: os dois projetos rodam ao mesmo tempo e os outros testes contam as fazendas
// das empresas A e B, que aqui nunca mudam.
const { test, expect } = require('@playwright/test');
const { dados, turmaDe, entrar, semRolagemHorizontal, acessivel } = require('./apoio.js');

async function conferirTela(pagina) {
  await semRolagemHorizontal(pagina);
  await acessivel(pagina);
}

// CPF com dígitos verificadores corretos, a partir de um número base inventado (o cadastro recusa CPF inválido).
function cpfSintetico(base) {
  const digitos = String(base).padStart(9, '0').split('').map(Number);
  for (const peso of [10, 11]) {
    const soma = digitos.reduce((total, digito, indice) => total + digito * (peso - indice), 0);
    digitos.push(((soma * 10) % 11) % 10);
  }
  return digitos.join('');
}

test('plataforma cria empresa; o Administrador cadastra, nomeia níveis, renomeia, arquiva e desarquiva', async ({ page }, informacoes) => {
  const projeto = informacoes.project.name;
  const nome = `Fazenda E2E ${projeto}`;
  const renomeada = `${nome} renomeada`;
  await entrar(page, dados.plataforma.cpf);

  await page.goto('/empresas/nova');
  await expect(page.getByRole('heading', { name: 'Nova empresa', level: 1 })).toBeVisible();
  await conferirTela(page);
  await page.getByLabel('Nome da empresa').fill(`Empresa E2E ${projeto}`);
  await page.getByLabel('Nome do primeiro Administrador').fill('Administrador E2E');
  await page.getByLabel('E-mail do Administrador').fill(`e2e-${projeto}@exemplo.test`);
  await page.getByLabel('CPF do Administrador').fill(cpfSintetico(projeto.startsWith('computador') ? 700000001 : 700000002));
  await page.getByRole('button', { name: 'Criar empresa' }).click();
  await expect(page.getByRole('heading', { name: 'Empresa criada', level: 1 })).toBeVisible();
  await expect(page.getByText('Anote a senha temporária agora')).toBeVisible();
  await conferirTela(page);
  await page.getByRole('link', { name: 'Abrir a empresa' }).click();

  await page.getByRole('link', { name: 'Nomes dos níveis da divisão' }).click();
  await expect(page.getByRole('heading', { name: 'Nomes dos níveis da divisão', level: 1 })).toBeVisible();
  await conferirTela(page);
  await page.getByLabel('Nome do nível 1').fill('Quadra');
  await page.getByRole('button', { name: 'Salvar nomes' }).click();

  await page.getByRole('link', { name: 'Cadastrar fazenda' }).click();
  await expect(page.getByRole('heading', { name: 'Nova fazenda', level: 1 })).toBeVisible();
  await conferirTela(page);
  await page.getByLabel('Nome da fazenda').fill('   ');
  await page.getByRole('button', { name: 'Cadastrar fazenda' }).click();
  await expect(page.getByText(/Informe um nome/)).toBeVisible();
  await expect(page.getByLabel('Nome da fazenda')).toHaveAttribute('aria-invalid', 'true');
  await conferirTela(page);
  await page.getByLabel('Nome da fazenda').fill(nome);
  await page.getByRole('button', { name: 'Cadastrar fazenda' }).click();
  await expect(page.getByRole('heading', { name: nome, level: 1, exact: true })).toBeVisible();
  await expect(page.getByText('Sem sub-áreas cadastradas.')).toBeVisible();
  await conferirTela(page);

  await page.getByRole('link', { name: 'Cadastrar sub-área' }).first().click();
  await expect(page.getByRole('heading', { name: 'Nova sub-área', level: 1 })).toBeVisible();
  await expect(page.getByLabel('Nome de quadra')).toBeVisible(); // o nome do nível configurado aparece na criação (R10)
  await conferirTela(page);
  await page.getByLabel('Nome de quadra').fill('Quadra E2E');
  await page.getByRole('button', { name: 'Cadastrar quadra' }).click();
  await expect(page.getByRole('link', { name: 'Quadra E2E' })).toBeVisible();

  await page.getByRole('link', { name: 'Renomear fazenda' }).click();
  await conferirTela(page);
  await page.getByLabel('Nome', { exact: true }).fill(renomeada);
  await page.getByRole('button', { name: 'Salvar nome' }).click();
  await expect(page.getByRole('heading', { name: renomeada, level: 1, exact: true })).toBeVisible();

  await page.getByRole('link', { name: 'Arquivar fazenda' }).click();
  await expect(page.getByText('Nada é apagado.')).toBeVisible();
  await conferirTela(page);
  await page.getByRole('button', { name: 'Arquivar' }).click();
  await expect(page.getByText('Esta fazenda está arquivada: só leitura.')).toBeVisible();
  await expect(page.getByRole('link', { name: 'Renomear fazenda' })).toHaveCount(0);
  await conferirTela(page);

  await page.goto('/arquivadas/');
  await expect(page.getByRole('link', { name: renomeada })).toBeVisible();
  await conferirTela(page);

  await page.getByRole('link', { name: 'Desarquivar' }).first().click();
  await page.getByRole('button', { name: 'Desarquivar' }).click();
  await expect(page.getByRole('heading', { name: renomeada, level: 1, exact: true })).toBeVisible(); // a página da fazenda, não a confirmação
  await expect(page.getByText('Esta fazenda está arquivada: só leitura.')).toHaveCount(0);
  await expect(page.getByRole('link', { name: 'Renomear fazenda' })).toBeVisible();
});

test('pessoa só de leitura não vê ações e recebe 403 por URL direta; sem acesso recebe 404', async ({ page }, informacoes) => {
  const turma = turmaDe(informacoes);
  const casa = `/empresa/${dados.empresa_a}/`;
  await entrar(page, turma.usuaria.cpf);
  await page.goto(`${casa}fazenda/${dados.fazendas_a[0]}/`);
  await expect(page.getByRole('link', { name: /^(Cadastrar|Renomear|Arquivar)/ })).toHaveCount(0);
  for (const caminho of ['fazenda/nova', 'editar', 'niveis', 'arquivar', `fazenda/${dados.fazendas_a[0]}/editar`]) {
    const resposta = await page.goto(`${casa}${caminho}`);
    expect(resposta.status(), caminho).toBe(403);
  }
  await page.context().clearCookies();
  await entrar(page, dados.sem_acesso.cpf);
  expect((await page.goto(`${casa}fazenda/nova`)).status()).toBe(404);
});
