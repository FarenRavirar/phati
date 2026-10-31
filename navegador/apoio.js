'use strict';
// Auxiliares dos testes de navegador. Os dados vêm de `navegador/dados.json`, gerado por
// `manage.py popular_sintetico` (dado inventado; o arquivo não é versionado).
const fs = require('node:fs');
const path = require('node:path');
const { expect } = require('@playwright/test');
const { violacoes } = require('./axe.js');

const dados = JSON.parse(fs.readFileSync(path.join(__dirname, 'dados.json'), 'utf8'));

// Cada projeto (tamanho de tela) usa as próprias pessoas: os testes aceitam convite e trocam senha.
function turmaDe(testInfo) {
  return testInfo.project.name.startsWith('desktop') ? dados.turmas.desktop : dados.turmas.celular;
}

async function entrar(pagina, cpf, senha = dados.senha) {
  await pagina.goto('/entrar');
  await pagina.getByLabel('CPF', { exact: true }).fill(cpf);
  await pagina.getByLabel('Senha', { exact: true }).fill(senha);
  await pagina.getByRole('button', { name: 'Entrar' }).click();
}

async function semRolagemHorizontal(pagina) {
  const cabe = await pagina.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
  expect(cabe, 'a página rola na horizontal').toBe(true);
}

async function acessivel(pagina) {
  expect(await violacoes(pagina), 'violações do axe (WCAG 2.2 AA)').toEqual([]);
}

// Em tela estreita o menu começa recolhido e o botão Menu o abre.
async function abrirMenu(pagina) {
  const botao = pagina.getByRole('button', { name: 'Menu' });
  if ((await botao.isVisible()) && (await botao.getAttribute('aria-expanded')) === 'false') await botao.click();
}

module.exports = { dados, turmaDe, entrar, semRolagemHorizontal, acessivel, abrirMenu };
