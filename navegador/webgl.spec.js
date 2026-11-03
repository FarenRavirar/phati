'use strict';
// WebGL2 no Chromium (spec 004 R16, A11): o MapLibre 6 exige WebGL2. Sem ele o mapa não abre e o teste do mapa falharia
// com um erro obscuro; este teste falha antes, dizendo a causa. Não precisa de login nem de dado.
const { test, expect } = require('@playwright/test');

test('o Chromium oferece WebGL2', async ({ page }) => {
  await page.goto('/entrar');
  const disponivel = await page.evaluate(() => document.createElement('canvas').getContext('webgl2') !== null);
  expect(disponivel, 'WebGL2 indisponível no Chromium: o mapa (MapLibre 6) não abre. Confira launchOptions.args em playwright.config.js.').toBe(true);
});
