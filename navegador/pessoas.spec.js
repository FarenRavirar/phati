'use strict';
// Gestão de pessoas (spec 003, R13 a R17, R30): convidar, convites enviados, redefinir senha, transferir a titularidade e
// revogar pelas telas, nos dois tamanhos, com axe e sem rolagem horizontal; e o acesso negado por URL direta. A plataforma
// cria uma empresa própria de cada projeto e muda só ela (como em `territorio.spec.js`): as outras empresas ficam como estão.
const { test, expect } = require('@playwright/test');
const { dados, turmaDe, entrar, semRolagemHorizontal, acessivel, cpfSintetico } = require('./apoio.js');

async function conferirTela(pagina) {
  await semRolagemHorizontal(pagina);
  await acessivel(pagina);
}

test('plataforma convida, reenvia, cancela, redefine senha, transfere a titularidade e revoga', async ({ page }, informacoes) => {
  const projeto = informacoes.project.name;
  const computador = projeto.startsWith('computador');
  // Nome e CPFs mudam a cada rodada: o banco de teste guarda a rodada anterior e o cadastro recusa nome e CPF repetidos.
  const rodada = 600000000 + (Date.now() % 90000000);
  const empresa = `Empresa Pessoas ${projeto} ${rodada}`;
  const cpfConvidada = cpfSintetico(rodada + (computador ? 1 : 2));
  await entrar(page, dados.plataforma.cpf);

  await page.goto('/empresas/nova');
  await page.getByLabel('Nome da empresa').fill(empresa);
  await page.getByLabel('Nome do primeiro Administrador').fill('Administrador Pessoas');
  await page.getByLabel('E-mail do Administrador').fill(`pessoas-${projeto}@exemplo.test`);
  await page.getByLabel('CPF do Administrador').fill(cpfSintetico(rodada + (computador ? 3 : 4)));
  await page.getByRole('button', { name: 'Criar empresa' }).click();
  await page.getByRole('link', { name: 'Abrir a empresa' }).click();

  await page.getByRole('link', { name: 'Pessoas', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Pessoas', level: 1 })).toBeVisible();
  await expect(page.getByText('Administrador Pessoas', { exact: true })).toBeVisible();
  await conferirTela(page);

  // CPF inválido: a recusa do serviço volta ao formulário, em aviso anunciado.
  await page.getByRole('link', { name: 'Convidar pessoa' }).first().click();
  await expect(page.getByRole('heading', { name: 'Convidar pessoa', level: 1 })).toBeVisible();
  await conferirTela(page);
  await page.getByLabel('Nome', { exact: true }).fill('Convidada Pessoas');
  await page.getByLabel('E-mail').fill(`convidada-${projeto}@exemplo.test`);
  await page.getByLabel('CPF').fill('123');
  await page.getByLabel('Cargo').selectOption({ label: 'Administrador' });
  await page.getByLabel('Onde vale').selectOption({ label: 'Empresa inteira' });
  await page.getByRole('button', { name: 'Enviar convite' }).click();
  await expect(page.getByRole('alert')).toBeVisible();
  await conferirTela(page);

  // CPF novo: a senha temporária aparece uma vez.
  await page.getByLabel('CPF').fill(cpfConvidada);
  await page.getByRole('button', { name: 'Enviar convite' }).click();
  await expect(page.getByRole('heading', { name: 'Convite enviado', level: 1 })).toBeVisible();
  await expect(page.getByText('Anote a senha temporária agora')).toBeVisible();
  await conferirTela(page);
  await page.getByRole('link', { name: 'Voltar às pessoas' }).click();
  await expect(page.getByText('Convidada Pessoas', { exact: true })).toBeVisible();
  await expect(page.getByText('Anote a senha temporária agora')).toHaveCount(0);

  // CPF que já existe: convite pendente, sem senha e sem dado da pessoa.
  await page.getByRole('link', { name: 'Convidar pessoa' }).first().click();
  await page.getByLabel('Nome', { exact: true }).fill('Qualquer Nome');
  await page.getByLabel('E-mail').fill('qualquer@exemplo.test');
  await page.getByLabel('CPF').fill(cpfConvidada);
  await page.getByLabel('Cargo').selectOption({ label: 'Usuário' });
  await page.getByLabel('Onde vale').selectOption({ label: 'Empresa inteira' });
  await page.getByRole('button', { name: 'Enviar convite' }).click();
  await expect(page.getByText('O convite foi enviado.')).toBeVisible();
  await expect(page.getByText('Anote a senha temporária agora')).toHaveCount(0);
  await page.getByRole('link', { name: 'Voltar às pessoas' }).click();

  await page.getByRole('link', { name: 'Convites enviados' }).click();
  await expect(page.getByRole('heading', { name: 'Convites enviados', level: 1 })).toBeVisible();
  await conferirTela(page);
  await page.getByRole('button', { name: /^Reenviar/ }).click(); // logo depois do envio: o intervalo recusa
  await expect(page.getByText('Aguarde antes de reenviar.')).toBeVisible();
  await conferirTela(page);
  await page.getByRole('button', { name: /^Cancelar/ }).click();
  await expect(page.getByText('Convite cancelado.')).toBeVisible();
  await expect(page.getByText('Nenhum convite sem resposta.')).toBeVisible();
  await conferirTela(page);

  // Redefinir a senha: só o link por e-mail, nenhuma senha na tela.
  await page.getByRole('link', { name: 'Voltar às pessoas' }).click();
  await page.getByRole('link', { name: 'Redefinir senha de Administrador Pessoas' }).click();
  await expect(page.getByText('Você não vê a senha nova.')).toBeVisible();
  await conferirTela(page);
  await page.getByRole('button', { name: 'Enviar link' }).click();
  await expect(page.getByRole('heading', { name: 'Redefinição pedida', level: 1 })).toBeVisible();
  await expect(page.getByText(/senha temporária/i)).toHaveCount(0);
  await conferirTela(page);
  await page.getByRole('link', { name: 'Voltar às pessoas' }).click();

  // Titularidade em duas etapas: só a segunda tem efeito.
  await page.getByRole('link', { name: 'Transferir a titularidade' }).click();
  await expect(page.getByText('Etapa 1 de 2')).toBeVisible();
  await conferirTela(page);
  await page.getByLabel('Novo titular').selectOption({ label: `Convidada Pessoas (convidada-${projeto}@exemplo.test)` });
  await page.getByLabel('Justificativa').fill('Troca de gestão do teste de navegador.');
  await page.getByRole('button', { name: 'Continuar' }).click();
  await expect(page.getByText('Etapa 2 de 2')).toBeVisible();
  await conferirTela(page);
  await page.getByLabel(/Para confirmar, digite o nome da empresa/).fill('nome errado');
  await page.getByRole('button', { name: 'Transferir titularidade' }).click();
  await expect(page.getByText('O nome digitado não é o da empresa.')).toBeVisible();
  await conferirTela(page);
  await page.getByLabel(/Para confirmar, digite o nome da empresa/).fill(empresa);
  await page.getByRole('button', { name: 'Transferir titularidade' }).click();
  await expect(page.getByText('Titularidade transferida.')).toBeVisible();

  // Revogar: a confirmação diz que a linha fica.
  await page.getByRole('link', { name: 'Revogar Administrador de Administrador Pessoas' }).click();
  await expect(page.getByText(/não é apagada/)).toBeVisible();
  await conferirTela(page);
  await page.getByRole('button', { name: 'Revogar acesso' }).click();
  await expect(page.getByText('Acesso revogado.')).toBeVisible();
  await expect(page.getByText('Administrador Pessoas', { exact: true })).toBeVisible(); // segue na lista, sem acesso ativo
  await conferirTela(page);
});

test('pessoa só de leitura recebe 403 por URL direta; sem acesso recebe 404', async ({ page }, informacoes) => {
  const turma = turmaDe(informacoes);
  const casa = `/empresa/${dados.empresa_a}/`;
  await entrar(page, turma.usuaria.cpf);
  for (const caminho of ['pessoas/', 'pessoas/convidar', 'pessoas/convites', 'titularidade']) {
    const resposta = await page.goto(`${casa}${caminho}`);
    expect(resposta.status(), caminho).toBe(403);
  }
  await page.context().clearCookies();
  await entrar(page, dados.sem_acesso.cpf);
  expect((await page.goto(`${casa}pessoas/`)).status()).toBe(404);
});

test('escolher a sub-área do convite em duas etapas, com filtro, leva ao formulário já com o lugar', async ({ page }) => {
  const casa = `/empresa/${dados.empresa_a}/`;
  await entrar(page, dados.plataforma.cpf);
  await page.goto(`${casa}pessoas/convidar`);
  await page.getByRole('link', { name: 'Escolher uma sub-área' }).click();
  await expect(page.getByRole('heading', { name: 'Escolher a fazenda', level: 1 })).toBeVisible();
  await conferirTela(page);
  await page.getByRole('link', { name: 'Fazenda Inventada A1' }).click();
  await expect(page.getByRole('heading', { name: 'Escolher a sub-área', level: 1 })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Fazenda Inventada A1 › Talhao 1', exact: true })).toBeVisible(); // cada item leva a trilha dos pais
  await expect(page.getByRole('link', { name: 'Fazenda Inventada A1 › Talhao 1 › Gleba 1 › Lote 1' })).toBeVisible();
  await conferirTela(page);
  await page.getByLabel('Filtrar pelo nome').fill('lote');
  await page.getByRole('button', { name: 'Filtrar' }).click();
  await expect(page.getByRole('link', { name: 'Fazenda Inventada A1 › Talhao 1 › Gleba 1 › Lote 1' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Fazenda Inventada A1 › Talhao 1', exact: true })).toHaveCount(0);
  await conferirTela(page);
  await page.getByRole('link', { name: /Lote 1$/ }).click();
  await expect(page.getByRole('heading', { name: 'Convidar pessoa', level: 1 })).toBeVisible();
  await expect(page.getByLabel('Onde vale')).toHaveValue(/^sub-area-\d+$/);
  await conferirTela(page);
});
