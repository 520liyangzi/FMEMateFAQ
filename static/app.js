'use strict';

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const state = {data: null, file: null, preview: null, columnsEdited: false, busy: new Set(), view: 'recommend'};
const columnLabels = {question_zh: '触发问题 · 中文', question_en: '触发问题 · 英文', object_zh: '对象 · 中文', object_en: '对象 · 英文', field_zh: '字段 · 中文', field_en: '字段 · 英文'};
const titles = {recommend: '需求推荐', catalog: '功能目录', import: '导入 Excel', settings: '别名与 AI'};

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}
function append(parent, ...children) { children.filter(Boolean).forEach((node) => parent.append(node)); return parent; }
function message(text, kind = '') {
  const box = $('#global-message');
  box.className = `notice ${kind}`;
  box.textContent = text;
  box.hidden = !text;
}
function localNotice(parent, text, kind = 'warning') { parent.append(el('div', `notice ${kind}`, text)); }
function apiError(data, fallback) {
  const detail = data.error || data.message || data.detail;
  return typeof detail === 'string' ? detail : fallback;
}
async function api(path, body, method = 'POST') {
  const response = await fetch(path, body === undefined ? {headers: {Accept: 'application/json'}, cache: 'no-store'} : {
    method, headers: {'Content-Type': 'application/json', Accept: 'application/json'}, body: JSON.stringify(body)
  });
  let data;
  try { data = await response.json(); } catch (_) { throw new Error(`服务返回了无效结果（HTTP ${response.status}）`); }
  if (!response.ok || data.error) throw new Error(apiError(data, `请求失败（HTTP ${response.status}）`));
  return data;
}
async function withBusy(key, button, label, action) {
  if (state.busy.has(key)) return;
  state.busy.add(key);
  const original = button ? [...button.childNodes].map((n) => n.cloneNode(true)) : [];
  if (button) { button.disabled = true; button.replaceChildren(el('span', 'busy-spinner'), document.createTextNode(label)); }
  try { await action(); }
  catch (error) { message(error.message || '操作失败，请重试。', 'error'); }
  finally { state.busy.delete(key); if (button) {button.disabled = false; button.replaceChildren(...original);} }
}
function setView(name) {
  if (!titles[name]) name = 'recommend';
  state.view = name;
  $$('.view').forEach((view) => {view.hidden = view.id !== `view-${name}`;});
  $$('.nav-item').forEach((button) => button.classList.toggle('active', button.dataset.view === name));
  $('#page-title').textContent = titles[name];
  history.replaceState(null, '', `#${name}`);
  if (name === 'catalog') renderCatalog();
}
function statsFor(catalog) {
  const functions = catalog?.functions || [];
  return {functions: functions.length, objects: functions.reduce((total, f) => total + (f.objects || []).length, 0), fields: functions.reduce((total, f) => total + (f.objects || []).reduce((sum, o) => sum + (o.fields || []).length, 0), 0)};
}
function statsNode(summary) {
  const box = el('div', 'stats-grid');
  [['functions', '预置功能'], ['objects', '对象关系'], ['fields', '字段关系']].forEach(([key, label]) => {
    append(box, append(el('div', 'stat'), el('div', 'stat-label', label), el('div', 'stat-value', Number(summary[key] || 0).toLocaleString())));
  });
  return box;
}
function sourceText(source) {
  if (!source) return '';
  if (Array.isArray(source)) source = source[0];
  if (typeof source === 'string') return source;
  return [source.sheet, source.row ? `第 ${source.row} 行` : ''].filter(Boolean).join(' · ');
}
function renderState(data) {
  state.data = data;
  const catalog = data.catalog || {functions: []};
  const summary = statsFor(catalog);
  $('#catalog-count').textContent = summary.functions;
  $('#demo-banner').hidden = !data.is_demo;
  const filename = catalog.metadata?.filename;
  $('#dataset-label').textContent = data.is_demo ? '示例功能目录' : filename || (summary.functions ? '已导入功能目录' : '尚未导入目录');
  const settings = data.settings || {};
  $('#claude-enabled').checked = !!settings.claude_enabled;
  $('#claude-command').value = JSON.stringify(settings.claude_command || ['claude'], null, 2);
  $('#claude-timeout').value = settings.claude_timeout_seconds || 45;
  $('#use-ai').disabled = !settings.claude_enabled;
  if (!settings.claude_enabled) $('#use-ai').checked = false;
  $('#ai-hint').textContent = settings.claude_enabled ? '通过本机 Claude CLI 辅助拆解需求' : '可在“别名与 AI”中启用';
  $('#aliases-json').value = JSON.stringify(data.aliases || {groups: []}, null, 2);
  renderCatalog();
}
function catalogEntry(fn, expanded = false) {
  const entry = el('details', 'catalog-entry');
  entry.open = expanded;
  const summary = el('summary');
  const heading = el('div');
  append(heading, el('h3', '', fn.question_zh || fn.question_en || '未命名问题'));
  if (fn.question_en && fn.question_zh) heading.append(el('p', 'question-en', fn.question_en));
  const objects = fn.objects || [];
  const count = objects.reduce((sum, o) => sum + (o.fields || []).length, 0);
  const provenance = sourceText(fn.sources);
  heading.append(el('p', 'catalog-meta', `${objects.length} 个对象 · ${count} 个字段${provenance ? ` · ${provenance}` : ''}`));
  summary.append(heading);
  entry.append(summary);
  const list = el('div', 'object-list');
  objects.forEach((object) => {
    const item = el('div', 'object-entry');
    const label = el('div', 'object-name', object.name_zh || object.name_en || '未命名对象');
    if (object.name_zh && object.name_en) label.append(el('span', '', object.name_en));
    const fields = el('div', 'fields');
    (object.fields || []).forEach((field) => {
      const tag = el('div', 'field-tag', field.name_zh || field.name_en || '未命名字段');
      if (field.name_zh && field.name_en) tag.append(el('span', '', field.name_en));
      const source = sourceText(field.sources);
      if (source) tag.title = source;
      fields.append(tag);
    });
    if (!object.fields?.length) fields.append(el('span', 'muted small', '未列出字段'));
    append(item, label, fields); list.append(item);
  });
  if (!objects.length) list.append(el('div', 'object-entry muted small', '此问题未列出对象与字段。'));
  entry.append(list);
  return entry;
}
function renderCatalog() {
  const functions = state.data?.catalog?.functions || [];
  const stats = statsNode(statsFor(state.data?.catalog));
  $('#catalog-stats').replaceChildren(...stats.childNodes);
  const query = $('#catalog-search').value.trim().toLocaleLowerCase();
  const filtered = functions.filter((fn) => !query || JSON.stringify(fn).toLocaleLowerCase().includes(query));
  $('#catalog-filter-count').textContent = `显示 ${filtered.length} / ${functions.length} 个功能`;
  const list = $('#catalog-list');
  list.replaceChildren();
  if (!filtered.length) {
    list.append(el('div', 'empty-state', functions.length ? '未找到相关问题、对象或字段。' : '目录为空。请先导入 Excel，或加载示例数据。'));
    return;
  }
  filtered.forEach((fn) => list.append(catalogEntry(fn)));
}
function requirementText(item) { return typeof item === 'string' ? item : item?.text || item?.requirement || item?.id || ''; }
async function copyText(text, button) {
  try {
    if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(text);
    else {
      const field = el('textarea'); field.value = text; field.style.position = 'fixed'; field.style.left = '-10000px';
      document.body.append(field); field.select(); const copied = document.execCommand('copy'); field.remove();
      if (!copied) throw new Error('复制失败');
    }
    const original = button.textContent; button.textContent = '已复制'; setTimeout(() => {button.textContent = original;}, 1600);
  } catch (_) { message('无法自动复制，请选中问题文字手动复制。', 'warning'); }
}
function copyButton(text, label) {
  const button = el('button', 'copy-button', label); button.type = 'button';
  button.addEventListener('click', () => copyText(text, button)); return button;
}
function evidenceTable(evidence, requirementMap) {
  const table = el('table', 'evidence-table');
  const head = el('thead'); const header = el('tr');
  ['需求', '匹配对象 / 字段', 'Excel 来源'].forEach((label) => header.append(el('th', '', label)));
  head.append(header); table.append(head);
  const body = el('tbody');
  evidence.forEach((item) => {
    const row = el('tr');
    row.append(el('td', '', item.requirement || requirementMap.get(item.requirement_id) || item.requirement_id || '问题匹配'));
    const path = el('td', 'evidence-path');
    const zh = [item.object_zh, item.field_zh].filter(Boolean).join(' / ');
    const en = [item.object_en, item.field_en].filter(Boolean).join(' / ');
    path.append(el('span', '', zh || en || '触发问题'));
    if (zh && en) path.append(el('span', 'evidence-en', en));
    const source = sourceText(item.source || item.sources);
    append(row, path, el('td', 'source', source || '目录记录'));
    body.append(row);
  });
  table.append(body); return table;
}
function renderResults(result) {
  const root = $('#results'); root.replaceChildren(); root.hidden = false; $('#welcome').hidden = true;
  const requirements = result.requirements || [];
  const requirementMap = new Map(requirements.map((item) => [item.id, requirementText(item)]));
  const recommendations = result.recommendations || [];
  const plan = result.plan || {function_ids: [], covered_requirement_ids: [], uncovered_requirement_ids: [], coverage: 0};
  const missing = new Set(plan.uncovered_requirement_ids || []);
  const heading = el('div', 'results-heading');
  append(heading, el('h2', '', '推荐结果'), el('span', '', String(result.mode || 'local').includes('claude') || String(result.mode || '').includes('ai') ? 'Claude 增强 + 目录匹配' : '本地目录匹配'));
  root.append(heading);
  const chips = el('div', 'requirement-list');
  requirements.forEach((item) => chips.append(el('span', `requirement-chip${missing.has(item.id) ? ' missing' : ''}`, requirementText(item) + (item.normalized_text ? `（AI：${item.normalized_text}）` : ''))));
  root.append(chips);
  (result.warnings || []).forEach((warning) => localNotice(root, typeof warning === 'string' ? warning : JSON.stringify(warning)));
  const planFunctions = (plan.function_ids || []).map((id) => recommendations.find((fn) => fn.function_id === id) || (state.data?.catalog?.functions || []).find((fn) => fn.id === id)).filter(Boolean);
  const coverage = Math.max(0, Math.min(1, Number(plan.coverage) || 0));
  const planPanel = el('div', `plan-panel${coverage < 1 ? ' partial' : ''}`);
  const planHead = el('div', 'plan-head');
  const planDescription = el('div');
  const title = !planFunctions.length ? '暂未找到可用功能' : coverage === 1 ? `使用 ${planFunctions.length} 个功能即可覆盖当前需求` : `找到 ${planFunctions.length} 个功能，可覆盖部分需求`;
  append(planDescription, el('h3', '', title), el('p', '', `${(plan.covered_requirement_ids || []).length} / ${requirements.length} 项需求有目录依据${plan.optimal === false ? ' · 当前为候选组合' : ''}`));
  const badge = el('div', 'coverage-badge', `${Math.round(coverage * 100)}%`); badge.append(el('small', '', '需求覆盖率'));
  append(planHead, planDescription, badge); planPanel.append(planHead);
  if (planFunctions.length) {
    const items = el('div', 'plan-functions');
    planFunctions.forEach((fn) => items.append(el('span', 'plan-function', fn.question_zh || fn.question_en || fn.function_id)));
    planPanel.append(items);
  }
  const unmatched = (result.unmatched_requirements || []).map(requirementText).filter(Boolean);
  const uncovered = [...missing].map((id) => requirementMap.get(id) || id);
  const missingTexts = [...new Set([...uncovered, ...unmatched])];
  if (missingTexts.length) planPanel.append(el('div', 'missing-note', `未覆盖：${missingTexts.join('、')}。可补充功能清单或专业词别名后重试。`));
  root.append(planPanel);
  recommendations.forEach((fn, index) => {
    const card = el('article', 'result-card');
    const top = el('div', 'card-top');
    const question = el('div', 'question-main');
    append(question, el('h3', '', fn.question_zh || fn.question_en || '预置问题'));
    if (fn.question_zh && fn.question_en) question.append(el('p', 'question-en', fn.question_en));
    append(top, el('span', 'rank', String(index + 1).padStart(2, '0')), question, el('span', 'coverage-label', `覆盖 ${Math.round((Number(fn.coverage) || 0) * 100)}%`));
    card.append(top);
    const actions = el('div', 'copy-actions');
    if (fn.question_zh) actions.append(copyButton(fn.question_zh, '复制中文问题'));
    if (fn.question_en) actions.append(copyButton(fn.question_en, '复制英文问题'));
    card.append(actions);
    card.append(el('div', 'evidence-title', '推荐依据'));
    if (fn.evidence?.length) card.append(evidenceTable(fn.evidence, requirementMap));
    else card.append(el('p', 'muted small', '触发问题与当前需求匹配。'));
    const ownMissing = (fn.missing_requirement_ids || []).map((id) => requirementMap.get(id) || id);
    if (ownMissing.length) card.append(el('p', 'missing-note', `此功能未覆盖：${ownMissing.join('、')}`));
    root.append(card);
  });
  if (!recommendations.length) root.append(el('div', 'empty-state', '试试使用字段名称或常用缩写描述需求，并确认 Excel 中已包含对应内容。'));
}
async function recommend() {
  const query = $('#query').value.trim();
  if (!query) { $('#query').focus(); return; }
  await withBusy('recommend', $('#search-button'), '正在查找…', async () => {
    message('');
    const result = await api('/api/recommend', {query, use_ai: $('#use-ai').checked});
    renderResults(result);
  });
}
function base64Buffer(buffer) {
  const bytes = new Uint8Array(buffer); const chunks = [];
  for (let offset = 0; offset < bytes.length; offset += 16384) chunks.push(String.fromCharCode(...bytes.subarray(offset, offset + 16384)));
  return btoa(chunks.join(''));
}
function clearPreview() { state.preview = null; $('#import-preview').hidden = true; $('#import-preview').replaceChildren(); }
function renderPreview(result) {
  state.preview = result;
  const root = $('#import-preview'); root.hidden = false; root.replaceChildren();
  const panel = el('div', 'panel');
  const heading = el('div', 'preview-heading'); append(heading, el('h2', '', '识别结果预览'), el('span', 'tag', '尚未替换当前目录')); panel.append(heading);
  panel.append(statsNode(statsFor(result.catalog)));
  panel.append(el('p', 'preview-caption', `工作表：${result.selected_sheet || result.catalog?.metadata?.sheet || '自动识别'} · ${result.header_row === 0 ? '无表头' : `表头行：${result.header_row ?? '自动'}`}。请检查问题、对象和字段的层级。`));
  if (result.warnings?.length) {
    const notice = el('div', 'notice warning'); notice.append(el('strong', '', `${result.warnings.length} 条识别提示`));
    const warnings = el('ul', 'warning-list'); result.warnings.forEach((item) => warnings.append(el('li', '', typeof item === 'string' ? item : item.message || JSON.stringify(item))));
    notice.append(warnings); panel.append(notice);
  }
  const functions = result.catalog?.functions || [];
  const list = el('div', 'preview-functions'); functions.slice(0, 50).forEach((fn, index) => list.append(catalogEntry(fn, index === 0)));
  panel.append(list);
  if (functions.length > 50) panel.append(el('p', 'preview-caption', `此处预览前 50 个功能，确认后可在功能目录查看全部 ${functions.length} 个功能。`));
  const footer = el('div', 'preview-footer');
  footer.append(el('span', '', '确认导入后，当前目录会替换为本次识别结果。'));
  const confirm = el('button', 'button primary', '确认导入'); confirm.disabled = !functions.length;
  confirm.addEventListener('click', () => withBusy('confirm-import', confirm, '正在导入…', async () => {
    const data = await api('/api/import/confirm', {preview_id: result.preview_id}); renderState(data); clearPreview();
    $('#results').hidden = true; $('#welcome').hidden = false;
    message(`导入成功，共 ${functions.length} 个预置功能。现在可以描述需求进行查找。`); setView('catalog');
  }));
  footer.append(confirm); panel.append(footer); root.append(panel);
}
async function previewImport() {
  if (!state.file) return;
  await withBusy('preview-import', $('#preview-button'), '正在识别…', async () => {
    message('');
    const columns = {};
    for (const key of Object.keys(columnLabels)) { const number = Number($(`#column-${key}`).value); if (!Number.isInteger(number) || number < 1 || number > 256) throw new Error('列号必须是 1 至 256 之间的整数。'); columns[key] = number; }
    if (new Set(Object.values(columns)).size !== 6) throw new Error('六个字段需要使用不同的列。');
    const request = {filename: state.file.name, content_base64: base64Buffer(await state.file.arrayBuffer())};
    if (state.columnsEdited) request.columns = columns;
    if ($('#import-sheet').value) request.sheet = $('#import-sheet').value;
    if ($('#header-row').value !== '') {request.header_row = Number($('#header-row').value); if (!Number.isInteger(request.header_row) || request.header_row < 0) throw new Error('表头行号必须是非负整数。');}
    const result = await api('/api/import/preview', request);
    const selector = $('#import-sheet'); const previous = selector.value;
    selector.replaceChildren(); const auto = el('option', '', '自动识别'); auto.value = ''; selector.append(auto);
    (result.sheets || []).forEach((sheet) => {const option = el('option', '', typeof sheet === 'string' ? sheet : sheet.name); option.value = typeof sheet === 'string' ? sheet : sheet.name; selector.append(option);});
    selector.value = result.selected_sheet || previous || '';
    if (result.columns) Object.entries(result.columns).forEach(([key, value]) => { const input = $(`#column-${key}`); if (input && Number.isInteger(value)) input.value = value; });
    renderPreview(result);
  });
}

$$('.nav-item').forEach((button) => button.addEventListener('click', () => setView(button.dataset.view)));
$$('[data-goto]').forEach((button) => button.addEventListener('click', () => setView(button.dataset.goto)));
$$('[data-query]').forEach((button) => button.addEventListener('click', () => {$('#query').value = button.dataset.query; $('#query').focus();}));
$('#search-form').addEventListener('submit', (event) => {event.preventDefault(); recommend();});
$('#query').addEventListener('keydown', (event) => {if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {event.preventDefault(); recommend();}});
$('#catalog-search').addEventListener('input', renderCatalog);
$('#preview-button').addEventListener('click', previewImport);
$('#import-file').addEventListener('change', () => {
  clearPreview(); message(''); state.file = $('#import-file').files[0] || null;
  state.columnsEdited = false;
  Object.keys(columnLabels).forEach((key, index) => {$(`#column-${key}`).value = index + 1;});
  $('#file-label').textContent = state.file ? state.file.name : '点击选择 Excel 或 CSV 文件';
  $('#preview-button').disabled = !state.file;
  $('#import-sheet').replaceChildren(); const option = el('option', '', '自动识别'); option.value = ''; $('#import-sheet').append(option);
  if (state.file && state.file.size > 20 * 1024 * 1024) { message('文件超过 20 MB，请拆分后再导入。', 'error'); state.file = null; $('#preview-button').disabled = true; }
});
$('#import-sheet').addEventListener('change', clearPreview);
$('#header-row').addEventListener('input', clearPreview);
Object.entries(columnLabels).forEach(([key, text], index) => {
  const label = el('label', '', text); const input = el('input'); input.type = 'number'; input.min = '1'; input.max = '256'; input.value = index + 1; input.id = `column-${key}`;
  input.addEventListener('input', () => {state.columnsEdited = true; clearPreview();}); label.append(input); $('#column-mapping').append(label);
});
$('#load-demo').addEventListener('click', () => withBusy('demo', $('#load-demo'), '正在加载…', async () => {
  if (state.data && !state.data.is_demo && !confirm('加载示例将替换当前功能目录。请先导出目录保留备份。是否继续？')) return;
  const data = await api('/api/demo', {}); renderState(data); clearPreview(); $('#results').hidden = true; $('#welcome').hidden = false;
  message('示例数据已加载。导入真实 Excel 后，推荐结果会按你的功能清单更新。'); setView('recommend');
}));
$('#aliases-form').addEventListener('submit', (event) => {
  event.preventDefault(); withBusy('aliases', $('#aliases-form button[type=submit]'), '正在保存…', async () => {
    let aliases; try {aliases = JSON.parse($('#aliases-json').value);} catch (_) {throw new Error('别名 JSON 格式不正确，请检查引号、逗号和括号。');}
    const data = await api('/api/aliases', {aliases}, 'PUT'); renderState(data); message('别名已保存，下次查询立即生效。');
  });
});
$('#settings-form').addEventListener('submit', (event) => {
  event.preventDefault(); withBusy('settings', $('#settings-form button[type=submit]'), '正在保存…', async () => {
    let command; try {command = JSON.parse($('#claude-command').value);} catch (_) {throw new Error('启动命令必须是 JSON 字符串数组，例如 ["claude"]。');}
    if (!Array.isArray(command) || !command.length || command.some((value) => typeof value !== 'string' || !value.trim())) throw new Error('启动命令必须是非空字符串数组，例如 ["claude"]。');
    const timeout = Number($('#claude-timeout').value);
    if (!Number.isInteger(timeout) || timeout < 5 || timeout > 120) throw new Error('超时时间应为 5 至 120 秒之间的整数。');
    const data = await api('/api/settings', {claude_enabled: $('#claude-enabled').checked, claude_command: command, claude_timeout_seconds: timeout}, 'PUT'); renderState(data); message('AI 设置已保存。查询时勾选“使用 Claude 增强理解”即可调用。');
  });
});
setView(location.hash.slice(1) || 'recommend');
api('/api/state').then(renderState).catch((error) => {message(`无法连接本地服务：${error.message}`, 'error'); $('#dataset-label').textContent = '连接失败';});
