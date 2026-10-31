'use strict';
// Testes de navegador (spec 002, R19): Chromium nos dois tamanhos exigidos pelo AGENTS.md
// (1280×720 e 320×568). O endereço vem do ambiente; o padrão é o nginx do compose do job.
const { defineConfig } = require('@playwright/test');

const baseURL = process.env.PHATI_URL_NAVEGADOR || 'http://127.0.0.1:8080';

module.exports = defineConfig({
  testDir: 'navegador',
  testMatch: '*.spec.js',
  fullyParallel: false,
  retries: 0,
  reporter: process.env.CI ? [['list'], ['github']] : 'list',
  use: { baseURL, trace: 'off' },
  projects: [
    { name: 'desktop-1280x720', use: { browserName: 'chromium', viewport: { width: 1280, height: 720 } } },
    { name: 'celular-320x568', use: { browserName: 'chromium', viewport: { width: 320, height: 568 } } },
  ],
});
