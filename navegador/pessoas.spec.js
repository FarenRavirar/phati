'use strict';
// Gestão de pessoas (spec 003, R13 a R17, R30): convidar, convites enviados, redefinir senha, transferir a titularidade e
// revogar pelas telas, nos dois tamanhos, com axe e sem rolagem horizontal; e o acesso negado por URL direta. A plataforma
// cria uma empresa própria de cada projeto e muda só ela (como em `territorio.spec.js`): as outras empresas ficam como estão.
const { test, expect } = require('@playwright/test');
const { dados, turmaDe, entrar, semRolagemHorizontal, acessivel, acessivelComMenuAberto, cpfSintetico, abrirMenu } = require('./apoio.js');

async function conferirTela(pagina) {
  await semRolagemHorizontal(pagina);
  await acessivel(pagina);
}

test('plataforma convida, reenvia, cancela, redefine senha, transfere a titularidade e revoga', async ({ page }, informacoes) => {
  const projeto = informacoes.project.name;
  const computador = projeto.startsWith('computador');
  // Nome e CPFs mudam a cada rodada: o banco de teste guarda a rodada anterior e o cadastro recusa nome e CPF repetidos.
  // Cada projeto usa uma base de 4 CPFs só dele (a rodada anda de 8 em 8): os dois projetos rodam ao mesmo tempo e nunca dividem CPF.
  const rodada = 600000000 + (Date.now() % 12000000) * 8 + (computador ? 0 : 4);
  const empresa = `Empresa Pessoas ${projeto} ${rodada}`;
  const cpfConvidada = cpfSintetico(rodada);
  await entrar(page, dados.plataforma.cpf);

  await page.goto('/empresas/nova');
  await page.getByLabel('Nome da empresa').fill(empresa);
  await page.getByLabel('Nome do primeiro Administrador').fill('Administrador Pessoas');
  await page.getByLabel('E-mail do Administrador').fill(`pessoas-${projeto}@exemplo.test`);
  await page.getByLabel('CPF do Administrador').fill(cpfSintetico(rodada + 1));
  await page.getByRole('button', { name: 'Criar empresa' }).click();
  await page.getByRole('link', { name: 'Abrir a empresa' }).click();

  // A página da empresa também tem um botão "Pessoas": o clique é no link do menu, com a gaveta aberta em 320.
  await abrirMenu(page);
  await page.getByRole('navigation', { name: 'Menu principal' }).getByRole('link', { name: 'Pessoas', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Pessoas', level: 1 })).toBeVisible();
  await expect(page.getByText('Administrador Pessoas', { exact: true })).toBeVisible();
  await conferirTela(page);

  // Diálogo (telas.md §6): abre com o clique e fecha com o x, Esc e Cancelar. Nada é enviado nesses caminhos.
  const dialogo = page.getByRole('dialog', { name: 'Convidar pessoa' });
  await page.getByRole('link', { name: 'Convidar pessoa' }).first().click();
  await expect(dialogo).toBeVisible();
  await conferirTela(page);
  // telas.md §6: o corpo rola dentro do diálogo e o rodapé fica à vista; Cancelar e Enviar convite cabem na janela.
  const janela = page.viewportSize();
  for (const nome of ['Cancelar', 'Enviar convite']) {
    const caixa = await dialogo.getByRole('button', { name: nome, exact: true }).boundingBox();
    expect(caixa, nome).not.toBeNull();
    expect(caixa.y + caixa.height, nome).toBeLessThanOrEqual(janela.height);
    expect(caixa.x + caixa.width, nome).toBeLessThanOrEqual(janela.width);
  }
  await expect(dialogo.getByText('O cargo vale só neste lugar e nas áreas abaixo dele.')).toBeVisible();
  await dialogo.getByRole('button', { name: 'Fechar' }).click();
  await expect(dialogo).toBeHidden();
  await page.getByRole('link', { name: 'Convidar pessoa' }).first().click();
  await page.keyboard.press('Escape');
  await expect(dialogo).toBeHidden();
  await page.getByRole('link', { name: 'Convidar pessoa' }).first().click();
  await dialogo.getByRole('button', { name: 'Cancelar' }).click();
  await expect(dialogo).toBeHidden();
  await expect(page.getByText('Convidada Pessoas', { exact: true })).toHaveCount(0);
  // CPF inválido: a recusa do serviço volta ao formulário, em aviso anunciado.
  await page.getByRole('link', { name: 'Convidar pessoa' }).first().click();
  await expect(dialogo).toBeVisible();
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
  await expect(page.getByText('Convite enviado. Ele vale por 7 dias.')).toBeVisible();
  await expect(page.getByText('Anote a senha temporária agora')).toHaveCount(0);
  await page.getByRole('link', { name: 'Voltar às pessoas' }).click();

  await page.getByRole('link', { name: /Convites pendentes/ }).click();
  await expect(page.getByRole('heading', { name: 'Pessoas', level: 1 })).toBeVisible();
  await expect(page.getByRole('link', { name: /Convites pendentes/ })).toHaveAttribute('aria-current', 'page');
  await conferirTela(page);
  // Convite de CPF que já existe vale 7 dias (D053, permissao/convite.py VALIDADE): "vale até" cai 7 dias depois de "Enviado em".
  const [, enviado, valeAte] = (await page.locator('.ag-convite-detalhe').first().innerText()).match(/Enviado em (\d{2}\/\d{2}\/\d{4}) · vale até (\d{2}\/\d{2}\/\d{4})/);
  const diaDe = (data) => { const [dia, mes, ano] = data.split('/').map(Number); return Date.UTC(ano, mes - 1, dia); };
  expect((diaDe(valeAte) - diaDe(enviado)) / 86400000).toBe(7);
  await page.getByRole('button', { name: /^Reenviar/ }).click(); // logo depois do envio: o intervalo recusa
  await expect(page.getByText('Aguarde antes de reenviar.')).toBeVisible();
  await conferirTela(page);
  await page.getByRole('button', { name: /^Cancelar/ }).click();
  await expect(page.getByText('Convite cancelado.')).toBeVisible();
  await expect(page.getByText('Nenhum convite sem resposta.')).toBeVisible();
  await conferirTela(page);

  // Redefinir a senha: só o link por e-mail, nenhuma senha na tela.
  // A lista de convites vazia não tem "Voltar às pessoas" (só o link de cada tela de resultado): a aba "Todas" volta.
  await page.getByRole('link', { name: /^Todas/ }).click();
  await expect(page.getByRole('heading', { name: 'Pessoas', level: 1 })).toBeVisible();
  await page.locator('summary[aria-label="Ações para Administrador Pessoas"]').click();
  await page.getByRole('link', { name: 'Redefinir senha', exact: true }).click();
  await expect(page.getByText('Você não vê a senha nova.')).toBeVisible();
  await conferirTela(page);
  await page.getByRole('button', { name: 'Enviar link' }).click();
  await expect(page.getByRole('heading', { name: 'Redefinição pedida', level: 1 })).toBeVisible();
  await expect(page.getByText(/senha temporária/i)).toHaveCount(0);
  await conferirTela(page);
  await page.getByRole('link', { name: 'Voltar às pessoas' }).click();

  // "mais N": a linha mostra 3 concessões e o resto abre no "mais N". Administrador Pessoas já tem 1 (criada com a empresa):
  // mais 3 pelo fluxo de conceder dão 4, e a 4ª fica atrás do "mais 1".
  for (const cargo of ['Curador', 'Técnico', 'Usuário']) {
    await page.locator('summary[aria-label="Ações para Administrador Pessoas"]').click();
    await page.getByRole('link', { name: 'Conceder cargo' }).first().click();
    await page.getByLabel('Cargo').selectOption({ label: cargo });
    await page.getByLabel('Onde vale').selectOption({ label: 'Empresa inteira' });
    await page.getByRole('button', { name: 'Conceder', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Pessoas', level: 1 })).toBeVisible();
  }
  await page.getByText('mais 1', { exact: true }).click();
  await expect(page.getByText(/^Usuário · /)).toBeVisible();
  await conferirTela(page);

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
  await page.locator('summary[aria-label="Ações para Administrador Pessoas"]').click();
  await page.getByRole('link', { name: 'Revogar Administrador · Empresa inteira', exact: true }).click();
  await expect(page.getByText(/não é apagada/)).toBeVisible();
  await conferirTela(page);
  await page.getByRole('button', { name: 'Revogar acesso' }).click();
  await expect(page.getByText('Acesso revogado.')).toBeVisible();
  await expect(page.getByText('Administrador Pessoas', { exact: true })).toBeVisible(); // segue na lista, sem acesso ativo
  await conferirTela(page);
});

test('menu "..." existe só onde há ação e abre com as ações', async ({ page }) => {
  await entrar(page, dados.plataforma.cpf);
  await page.goto(`/empresa/${dados.empresa_a}/pessoas/`);
  // Administrador da plataforma tem ação em cada linha: o menu abre e mostra Redefinir senha.
  const menu = page.locator('summary[aria-label^="Ações para"]').first();
  await menu.click();
  await expect(page.getByRole('link', { name: 'Redefinir senha', exact: true }).first()).toBeVisible();
  // Com o menu aberto ele cobre alvos da página: o helper conta isso (ver apoio.js, acessivelComMenuAberto).
  await semRolagemHorizontal(page);
  await acessivelComMenuAberto(page);
});

test.describe('sem JavaScript', () => {
  test.use({ javaScriptEnabled: false });
  test('o link Convidar pessoa leva à página do convite', async ({ page }) => {
    await entrar(page, dados.plataforma.cpf);
    await page.goto(`/empresa/${dados.empresa_a}/pessoas/`);
    await page.getByRole('link', { name: 'Convidar pessoa' }).first().click();
    await expect(page).toHaveURL(/\/pessoas\/convidar$/);
    await expect(page.getByRole('heading', { name: 'Convidar pessoa', level: 1 })).toBeVisible();
  });
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
