'use strict';
// Testes de navegador (spec 002, R19): Chromium nos dois tamanhos exigidos pelo AGENTS.md
// (1280×720 e 320×568). O endereço vem do ambiente; o padrão é o nginx do compose do job.
const { defineConfig } = require('@playwright/test');

const baseURL = process.env.PHATI_URL_NAVEGADOR || 'http://127.0.0.1:8080';

// WebGL2 por software (spec 004 R16, T0.4): o MapLibre exige WebGL2 e o runner do Actions não tem GPU. Fallback documentado
// pelo Chromium (docs/gpu/swiftshader.md); medido localmente em 2026-11-03 que WebGL2 já vem ligado sem estas opções e que
// com elas segue ligado. O Playwright 1.64.1 já acrescenta `--enable-unsafe-swiftshader`; as outras duas fixam o caminho.
// O que o runner Linux de fato precisa fica registrado na T1.11.
const argumentosWebgl = ['--use-gl=angle', '--use-angle=swiftshader-webgl', '--enable-unsafe-swiftshader'];

// Fundo Google (spec 004 Fase 3): a prova exige o servidor com a flag do Google ligada, então roda à parte
// (`PHATI_PROVA_GOOGLE=1`) e fica fora da rodada comum, que sobe sem a flag.
const soGoogle = process.env.PHATI_PROVA_GOOGLE === '1';

// `testIgnore` de projeto substitui o da raiz (não soma), então cada projeto repete a exclusão da prova do Google.
const foraDaRodadaComum = soGoogle ? [] : [/fundo-google\.spec\.js$/];

module.exports = defineConfig({
  testDir: 'navegador',
  testMatch: soGoogle ? 'fundo-google.spec.js' : '*.spec.js',
  testIgnore: foraDaRodadaComum,
  fullyParallel: false,
  retries: 0,
  reporter: process.env.CI ? [['list'], ['github']] : 'list',
  use: { baseURL, trace: 'off' },
  projects: [
    { name: 'computador-1280x720', testIgnore: foraDaRodadaComum, use: { browserName: 'chromium', viewport: { width: 1280, height: 720 }, launchOptions: { args: argumentosWebgl } } },
    { name: 'celular-320x568', testIgnore: [/zoom\.spec\.js$/, ...foraDaRodadaComum], use: { browserName: 'chromium', viewport: { width: 320, height: 568 }, launchOptions: { args: argumentosWebgl } } },
  ],
});
