import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');

test('production HTML does not rely on Tailwind CDN and provides a favicon', () => {
  assert.equal(html.includes('cdn.tailwindcss.com'), false);
  assert.match(html, /<link\s+rel="icon"\s+href="data:image\/svg\+xml,/);
});

test('shape creation controls are semantic buttons', () => {
  const shapeButtons = html.match(/<button\s+type="button"\s+class="shape-btn"/g) ?? [];
  assert.equal(shapeButtons.length, 15);
  assert.equal(/<div\s+class="shape-btn"/.test(html), false);
});

test('mobile drawer synchronizes visual and accessibility state', () => {
  assert.match(html, /id="sidebar"/);
  assert.match(html, /aria-controls="sidebar"/);
  assert.match(html, /function\s+setSidebarOpen/);
  assert.match(html, /setAttribute\('inert'/);
  assert.match(html, /removeAttribute\('inert'\)/);
  assert.match(html, /--drawer-width:\s*min\(300px,\s*86vw\)/);
});

test('practice dialog exposes modal semantics and focuses the answer input', () => {
  assert.match(html, /role="dialog"/);
  assert.match(html, /aria-modal="true"/);
  assert.match(html, /practiceAnswer'\)\.focus\(\)/);
});

test('calculation UI uses shared geometry computation helpers', () => {
  assert.match(html, /function\s+getGeometryComputation/);
  assert.match(html, /function\s+getShapeParams/);
  assert.match(html, /const computation = getGeometryComputation\(data\)/);
  assert.match(html, /const computation = getGeometryComputation\(d\)/);
});

test('formula expansion uses an accessible button state', () => {
  assert.match(html, /class="formula-toggle"/);
  assert.match(html, /aria-expanded="false"/);
  assert.match(html, /setAttribute\('aria-expanded', 'true'\)/);
});

test('desktop right mouse drag is reserved for camera rotation', () => {
  assert.match(html, /RIGHT:\s*THREE\.MOUSE\.ROTATE/);
  assert.match(html, /function\s+handleCanvasPointerDown/);
  assert.match(html, /e\.button === 2[\s\S]*dragControls\.enabled = false/);
  assert.match(html, /function\s+restoreDragControls/);
  assert.equal(html.includes('stopImmediatePropagation()'), false);
});
