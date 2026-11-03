'use strict';
// Auxiliares dos testes de navegador. Os dados vêm de `navegador/dados.json`, gerado por
// `manage.py popular_sintetico` (dado inventado; o arquivo não é versionado).
const fs = require('node:fs');
const path = require('node:path');
const { expect } = require('@playwright/test');
const { violacoes } = require('./axe.js');

// Leitura preguiçosa: o teste do próprio auxiliar (`apoio.test.js`) roda no job de testes, que não tem `dados.json`.
let memoria;
function lerDados() {
  memoria ??= JSON.parse(fs.readFileSync(path.join(__dirname, 'dados.json'), 'utf8'));
  return memoria;
}

// Cada projeto (tamanho de tela) usa as próprias pessoas: os testes aceitam convite, trocam senha e erram a senha.
// O nome do projeto começa pelo da turma; projeto sem turma é erro, não cai numa turma por padrão.
function turmaDe(informacoesDoTeste, dados = lerDados()) {
  const nomeDoProjeto = informacoesDoTeste.project.name;
  const turma = Object.keys(dados.turmas).find((nome) => nomeDoProjeto.startsWith(nome));
  if (turma === undefined) throw new Error(`projeto "${nomeDoProjeto}" sem turma em dados.json: ${Object.keys(dados.turmas)}`);
  return dados.turmas[turma];
}

async function entrar(pagina, cpf, senha = lerDados().senha) {
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

// CPF com dígitos verificadores corretos, a partir de um número base inventado (o cadastro recusa CPF inválido).
function cpfSintetico(base) {
  const digitos = String(base).padStart(9, '0').split('').map(Number);
  for (const peso of [10, 11]) {
    const soma = digitos.reduce((total, digito, indice) => total + digito * (peso - indice), 0);
    digitos.push(((soma * 10) % 11) % 10);
  }
  return digitos.join('');
}

// Em tela estreita o menu começa recolhido e o botão Menu o abre.
async function abrirMenu(pagina) {
  const botao = pagina.getByRole('button', { name: 'Menu' });
  if ((await botao.isVisible()) && (await botao.getAttribute('aria-expanded')) === 'false') await botao.click();
}

// Rede externa (spec 004 R16): `true` quando a URL não é do próprio app. `data:` e `blob:` não saem do navegador.
function ehExterna(url, base) {
  const alvo = new URL(url);
  if (alvo.protocol === 'data:' || alvo.protocol === 'blob:' || alvo.protocol === 'about:') return false;
  return alvo.host !== new URL(base).host;
}

// Registra cada requisição da página; devolve a lista (viva) das externas. Quem chama confere que ficou vazia.
function observarRequisicoesExternas(pagina, base) {
  const externas = [];
  pagina.on('request', (requisicao) => {
    if (ehExterna(requisicao.url(), base)) externas.push(requisicao.url());
  });
  return externas;
}

module.exports = {
  ehExterna,
  observarRequisicoesExternas,
  get dados() {
    return lerDados();
  },
  turmaDe,
  entrar,
  semRolagemHorizontal,
  acessivel,
  abrirMenu,
  cpfSintetico,
};
