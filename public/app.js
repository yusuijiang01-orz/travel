import { destinations, sources } from './destinations.js';

const $ = selector => document.querySelector(selector);
const tabs = $('#tabs');
const panel = $('#destination');
const dialog = $('#poll-dialog');
const form = $('#poll-form');
const message = $('#poll-message');
let activeId;
let submitted = false;
const escapeHtml = value => String(value).replace(/[&<>"']/g, character => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[character]));
const external = (label, url) => `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(label)} ↗</a>`;
const mapUrl = name => `https://uri.amap.com/search?keyword=${encodeURIComponent(name)}&city=${encodeURIComponent('龙岩')}&view=map&src=family-travel`;

tabs.innerHTML = destinations.map((destination, index) => `<button type="button" class="tab" role="tab" id="tab-${destination.id}" data-id="${destination.id}" aria-controls="destination" aria-selected="false" tabindex="-1"><span class="tab-index">0${index + 1}</span>${escapeHtml(destination.short)}</button>`).join('');

function renderDestination(id, focus = false) {
  const destination = destinations.find(item => item.id === id) || destinations[0];
  activeId = destination.id;
  for (const button of tabs.querySelectorAll('button')) {
    const selected = button.dataset.id === activeId;
    button.setAttribute('aria-selected', String(selected)); button.tabIndex = selected ? 0 : -1;
  }
  panel.setAttribute('aria-labelledby', `tab-${activeId}`);
  const picture = destination.photo;
  const visual = picture ? `<figure class="hero-photo"><span class="photo-label">${escapeHtml(picture.subject)}</span><img src="${escapeHtml(picture.url)}" alt="${escapeHtml(picture.alt)}" fetchpriority="high" width="800" height="600"><figcaption>${escapeHtml(picture.subject)} · ${external(picture.author, picture.source)} · 页面裁切展示</figcaption></figure>`
    : `<aside class="hero-fieldnote" aria-label="路线示意插图，非实景照片"><span class="large-index" aria-hidden="true">0${destinations.indexOf(destination) + 1}</span><h3>${escapeHtml(destination.name)}</h3><svg class="locator-drawing" viewBox="0 0 300 72" role="img" aria-label="从湖雷到公园，再到街区的路线示意，不按比例"><path d="M22 35C66 35 75 12 130 35S218 58 278 35" fill="none" stroke="currentColor" stroke-width="2" stroke-dasharray="4 6"/><circle cx="22" cy="35" r="5" fill="currentColor"/><circle cx="150" cy="40" r="5" fill="currentColor"/><circle cx="278" cy="35" r="5" fill="currentColor"/><text x="4" y="66">湖雷</text><text x="134" y="18">公园</text><text x="263" y="66">街区</text></svg><p>简绘路线示意 · 非现场照片 · 不按比例<br>停车点与两处通行路线以当日地图为准。</p><div class="note-lines"><span>湖雷镇出发</span><span>6 人同行</span></div></aside>`;
  panel.innerHTML = `<div class="hero"><div class="hero-copy"><p class="destination-category">${escapeHtml(destination.category)}</p><h2>${escapeHtml(destination.headline)}</h2><p>${escapeHtml(destination.description)}</p><div class="hero-actions"><a class="button primary" href="${mapUrl(destination.map)}" target="_blank" rel="noopener noreferrer">地图搜目的地 <span aria-hidden="true">↗</span></a><a class="button" href="#itinerary">看看怎么安排 <span aria-hidden="true">↓</span></a></div></div>${visual}</div>
    <div class="fact-strip">${[['湖雷出发 · 自驾粗估', destination.drive], ['舒服的停留时间', destination.stay], ['带宝宝怎么逛', destination.baby], ['这趟旅行的节奏', destination.season]].map(([label, value]) => `<div class="fact"><small>${escapeHtml(label)}</small><strong>${escapeHtml(value)}</strong></div>`).join('')}</div>
    <p class="traffic-note">车程只是粗略规划区间，未作实时测算；天气、假日与停车会增加时间。点击地图后，把出发地设为“永定湖雷镇”，以当日路线为准。${destination.secondMap ? ' ' + external('另一处：' + destination.secondMap, mapUrl(destination.secondMap)) : ''}</p>
    <div class="editor-note"><strong>为什么选这里</strong><p>${escapeHtml(destination.recommendation)}</p></div>
    <div class="section-heading"><div><p class="eyebrow">TAKE A CLOSER LOOK / ${escapeHtml(destination.english)}</p><h2>值得停下来的地方</h2></div><span class="mini-label">轻松看 · 慢慢逛</span></div>
    <div class="detail-grid"><div class="highlights">${destination.highlights.map(([title, description], index) => `<article class="highlight"><span class="highlight-number">0${index + 1}</span><div><h3>${escapeHtml(title)}</h3><p>${escapeHtml(description)}</p></div></article>`).join('')}</div>
    <aside class="baby-card"><h3>一岁宝宝同行 <span>照顾好小旅人</span></h3><ol>${destination.logistics.map(item => `<li>${escapeHtml(item)}</li>`).join('')}</ol><p class="baby-caution"><strong>这一点先记住</strong>${escapeHtml(destination.caution)}</p></aside></div>
    <section id="itinerary" class="itinerary-section" aria-labelledby="itinerary-title"><div class="section-heading"><div><p class="eyebrow">A DAY AT YOUR OWN PACE</p><h2 id="itinerary-title">一天怎么安排？</h2></div><span class="mini-label">时间可随宝宝调整</span></div><div class="timeline">${destination.timeline.map(([time, title, description]) => `<article class="timeline-item"><time>${escapeHtml(time)}</time><h3>${escapeHtml(title)}</h3><p>${escapeHtml(description)}</p></article>`).join('')}</div><div class="departure-check"><strong>出门前的小检查</strong><div><p>随身带：${escapeHtml(destination.pack)}</p><p>提前问：${escapeHtml(destination.confirm)}</p></div></div><div class="destination-sources">${destination.sourceLinks.map(([label, url]) => external(label, url)).join('')}</div></section>`;
  const image = panel.querySelector('.hero-photo img');
  image?.addEventListener('error', () => {
    image.remove(); const note = document.createElement('p'); note.className = 'image-unavailable';
    note.textContent = '实景照片暂时未加载，可通过下方署名打开图片来源。'; panel.querySelector('.hero-photo').append(note);
  }, { once: true });
  if (focus) $(`#tab-${activeId}`).focus();
}

tabs.addEventListener('click', event => {
  const button = event.target.closest('[data-id]');
  if (button) location.hash = button.dataset.id;
});
tabs.addEventListener('keydown', event => {
  const index = destinations.findIndex(item => item.id === activeId);
  let next;
  if (event.key === 'ArrowRight') next = (index + 1) % destinations.length;
  if (event.key === 'ArrowLeft') next = (index - 1 + destinations.length) % destinations.length;
  if (event.key === 'Home') next = 0;
  if (event.key === 'End') next = destinations.length - 1;
  if (next === undefined) return;
  event.preventDefault(); const id = destinations[next].id;
  history.replaceState(null, '', `#${id}`); renderDestination(id, true);
});
addEventListener('hashchange', () => {
  const id = location.hash.slice(1);
  if (destinations.some(item => item.id === id)) renderDestination(id);
});
renderDestination(location.hash.slice(1));
$('#source-links').innerHTML = [['东南网 · 澜溪鹦鹉园报道（2026）', sources.parrot], ['畅游龙岩 · 培斜乡村休闲', sources.peixie], ['福建省文旅厅 · 培斜村资料（2019）', sources.village], ['龙岩城管 · 公园资料（2024）', sources.parks], ['永定区政府 · 凤城夜市文旅方案（2026）', sources.plan]].map(([label, url]) => `<li>${external(label, url)}</li>`).join('');

$('#poll-options').innerHTML = destinations.map(destination => `<label class="poll-option"><input type="radio" name="candidate" value="${destination.id}"><span><strong>${escapeHtml(destination.name)}</strong><small>${escapeHtml(destination.category)}</small></span></label>`).join('');
const selected = () => [...form.querySelectorAll('[name=candidate]:checked')].map(input => input.value);
const mode = () => form.elements.mode.value;
function setMessage(text, kind = '') { message.textContent = text; message.dataset.kind = kind; }
function updateCounter() { $('#selection-count').textContent = `已选 ${selected().length} / ${mode() === 'single' ? 1 : 3}`; }
form.addEventListener('change', event => {
  if (event.target.name === 'mode') {
    const retained = selected().slice(0, mode() === 'single' ? 1 : 3);
    form.querySelectorAll('[name=candidate]').forEach(input => { input.type = mode() === 'single' ? 'radio' : 'checkbox'; input.checked = retained.includes(input.value); });
  }
  if (selected().length > 3) { event.target.checked = false; setMessage('多选最多选择 3 个目的地。', 'error'); }
  else if (!submitted) setMessage('');
  updateCounter();
});

async function request(path, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 10000);
  try {
    const response = await fetch(path, { ...options, signal: controller.signal, cache: 'no-store' });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '服务暂时不可用，请稍后重试。');
    return data;
  } catch (error) {
    if (error.name === 'AbortError' || error instanceof TypeError) throw new Error('网络暂时没有连上，请稍后再试。');
    throw error;
  } finally { clearTimeout(timer); }
}

function showResults(results) {
  const target = 5;
  const extra = results.voters > target ? ' · 已超过本次同行大人数，包含其他访客投票' : '';
  $('#results-summary').textContent = results.voters ? `已收 ${results.voters} 人的选择 · ${results.selections} 票${extra}` : '还没有人投票，来留下第一份选择吧。';
  $('#results-bars').innerHTML = destinations.map(destination => {
    const votes = results.totals[destination.id] || 0;
    const percent = results.voters ? Math.round(votes / results.voters * 100) : 0;
    return `<div class="result-row"><div class="result-text"><span>${escapeHtml(destination.name)}</span><span>${votes} 票 · ${percent}%</span></div><div class="result-track" role="meter" aria-label="${escapeHtml(destination.name)}支持比例" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${percent}"><div class="result-fill" data-percent="${percent}"></div></div></div>`;
  }).join('');
  $('#results-bars').querySelectorAll('.result-fill').forEach(bar => { bar.style.width = `${bar.dataset.percent}%`; });
}
async function refreshResults() {
  const button = $('#refresh-results'); button.disabled = true;
  try { showResults(await request('/api/results')); }
  catch (error) { $('#results-summary').textContent = `${error.message} 点击“刷新”重试。`; }
  finally { button.disabled = false; }
}
function openPoll() { dialog.showModal(); document.body.classList.add('poll-open'); refreshResults(); }
$('#open-poll').addEventListener('click', openPoll);
document.querySelectorAll('.open-poll').forEach(button => button.addEventListener('click', openPoll));
$('#close-poll').addEventListener('click', () => dialog.close());
dialog.addEventListener('close', () => document.body.classList.remove('poll-open'));
dialog.addEventListener('click', event => {
  const box = dialog.getBoundingClientRect();
  if (event.target === dialog && (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom)) dialog.close();
});
$('#refresh-results').addEventListener('click', refreshResults);

form.addEventListener('submit', async event => {
  event.preventDefault();
  if (submitted) return;
  const choices = selected();
  if (!choices.length) return setMessage('先选一个想去的目的地吧。', 'error');
  const button = $('#submit-poll'); button.disabled = true; setMessage('正在提交，请稍等…');
  try {
    const result = await request('/api/votes', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ nickname: $('#nickname').value, candidates: choices, mode: mode() }) });
    submitted = true;
    setMessage(result.message, 'success'); showResults(result.results);
    button.textContent = '已提交，谢谢你的选择';
    for (const input of form.querySelectorAll('input')) input.disabled = true;
    // This remembers the submitted form only. Shared votes always come from the server.
    try { localStorage.setItem('family-travel-ballot-v1', JSON.stringify({ nickname: $('#nickname').value, candidates: choices, mode: mode() })); } catch {}
  } catch (error) { setMessage(error.message, 'error'); button.disabled = false; }
});
try {
  const remembered = JSON.parse(localStorage.getItem('family-travel-ballot-v1') || 'null');
  if (remembered && typeof remembered.nickname === 'string') $('#nickname').value = remembered.nickname;
} catch {}
