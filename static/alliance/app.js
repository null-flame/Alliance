'use strict';

const $ = id => document.getElementById(id);
const APP = $('app');

const state = {
  site: null,
  sections: [],
  stats: { total_allies: 0, active_allies: 0, total_posts: 0 },
  sectionMap: {},
  loaded: false,
  admin: loadAdmin(),
};

/* ══════════════════════════════════════════════════
   Admin persistence
   ══════════════════════════════════════════════════ */
function loadAdmin() {
  try {
    const raw = localStorage.getItem('alliance_admin');
    if (!raw) return { token: null, section_id: null, username: null, section_name: null };
    return JSON.parse(raw);
  } catch {
    return { token: null, section_id: null, username: null, section_name: null };
  }
}
function saveAdmin(a) {
  state.admin = a;
  if (a.token) localStorage.setItem('alliance_admin', JSON.stringify(a));
  else localStorage.removeItem('alliance_admin');
}

/* ══════════════════════════════════════════════════
   API
   ══════════════════════════════════════════════════ */
async function api(url, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  if (state.admin.token) headers['X-Alliance-Token'] = state.admin.token;
  if (opts.body && typeof opts.body !== 'string') {
    headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(opts.body);
  }
  const r = await fetch(url, { ...opts, headers });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const err = new Error(data.error || `HTTP ${r.status}`);
    err.status = r.status;
    throw err;
  }
  return data;
}

/* ══════════════════════════════════════════════════
   Toast
   ══════════════════════════════════════════════════ */
let toastTimer = null;
function toast(msg, kind = '') {
  const t = $('toast');
  if (!t) return;
  t.textContent = msg;
  t.className = `toast show ${kind}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.className = 'toast', 3000);
}

/* ══════════════════════════════════════════════════
   Theme
   ══════════════════════════════════════════════════ */
function applyTheme() {
  let t = localStorage.getItem('alliance_theme');
  if (!t) t = window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', t);
  const btn = $('themeBtn');
  if (btn) btn.textContent = t === 'dark' ? '◐' : '☀';
}
function wireTheme() {
  const btn = $('themeBtn');
  if (!btn) return;
  btn.addEventListener('click', () => {
    const cur = document.documentElement.getAttribute('data-theme');
    const next = cur === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('alliance_theme', next);
    btn.textContent = next === 'dark' ? '◐' : '☀';
  });
}

/* ══════════════════════════════════════════════════
   Site meta
   ══════════════════════════════════════════════════ */
async function loadSite() {
  const data = await api('/api/alliance/site');
  state.site = data.site;
  state.sections = data.sections;
  state.stats = data.stats || {
    total_allies: data.sections.length,
    active_allies: 0,
    total_posts: 0,
  };
  state.sectionMap = {};
  data.sections.forEach(s => { state.sectionMap[s.id] = s; });
  state.loaded = true;

  const sn = $('site-name');
  const fn = $('footer-name');
  if (sn) sn.textContent = data.site.name;
  if (fn) fn.textContent = data.site.name;
  document.title = data.site.name;
}

/* ══════════════════════════════════════════════════
   Router
   ══════════════════════════════════════════════════ */
function route() {
  const path = window.location.pathname;
  document.querySelectorAll('#nav-home').forEach(a =>
    a.classList.toggle('active', path === '/'));

  if (path === '/' || path === '') return renderHome();
  if (path === '/admin') return renderAdmin();
  if (path === '/admin/panel') return renderAdminPanel();

  const m = path.match(/^\/s\/([^/]+)(?:\/([^/]+))?$/);
  if (m) {
    const sectionId = decodeURIComponent(m[1]);
    if (m[2]) return renderPost(sectionId, decodeURIComponent(m[2]));
    return renderSection(sectionId);
  }
  render404();
}

/* ══════════════════════════════════════════════════
   HOME
   ══════════════════════════════════════════════════ */
async function renderHome() {
  APP.innerHTML = '<div class="empty"><div class="icon">◈</div><p>Loading…</p></div>';
  try {
    if (!state.loaded) await loadSite();

    const allyCards = state.sections.map(allyCardHTML).join('') ||
      '<div class="empty"><div class="icon">◈</div><p>No allies registered.</p></div>';

    document.title = state.site.name;

    APP.innerHTML = `
      <div class="hero-coalition">
        <span class="mark-big" aria-hidden="true">◈</span>
        <div class="tagline">COALITION PORTAL</div>
        <h1>${esc(state.site.name)}</h1>
        <p>${esc(state.site.description || '')}</p>
        <div class="coalition-stats">
          <div class="stat">
            <div class="stat-value">${state.stats.total_allies}</div>
            <div class="stat-label">Allied Groups</div>
          </div>
          <div class="stat">
            <div class="stat-value">${state.stats.active_allies}</div>
            <div class="stat-label">Active</div>
          </div>
          <div class="stat">
            <div class="stat-value">${state.stats.total_posts}</div>
            <div class="stat-label">Intel Reports</div>
          </div>
        </div>
      </div>

      <div class="coalition-title">
        <h2 class="section-title">🛡 Allied Guards &amp; Groups
          <span class="count">${state.sections.length}</span>
        </h2>
        <a href="/admin" class="coalition-admin-link">Admin Access →</a>
      </div>

      <div class="allies-grid">${allyCards}</div>
    `;
  } catch (e) {
    APP.innerHTML = `<div class="empty"><div class="icon">⚠</div><p>${esc(e.message)}</p></div>`;
  }
}

function allyCardHTML(s) {
  return `
    <a class="ally-card" href="/s/${esc(s.id)}"
       style="--ally-color:${esc(s.color || '#4fd1c5')}">
      <div class="ally-emblem">
        ${s.image
          ? `<img src="${esc(s.image)}" alt="${esc(s.name)}" loading="lazy">`
          : `<div class="emblem-placeholder">◈</div>`}
      </div>
      <div class="ally-body">
        <h3 class="ally-name">${esc(s.name)}</h3>
        <p class="ally-desc">${esc(s.desc)}</p>
        <div class="ally-footer">
          <span class="ally-stat">
            <span class="ally-stat-num">${s.post_count ?? 0}</span>
            <span class="ally-stat-label">reports</span>
          </span>
          <span class="ally-enter">Enter →</span>
        </div>
      </div>
    </a>`;
}

/* ══════════════════════════════════════════════════
   SECTION
   ══════════════════════════════════════════════════ */
async function renderSection(sectionId) {
  APP.innerHTML = '<div class="empty"><div class="icon">◈</div><p>Loading…</p></div>';
  try {
    if (!state.loaded) await loadSite();
    const data = await api(`/api/alliance/sections/${encodeURIComponent(sectionId)}`);
    const sec = data.section;
    const cards = data.posts.length
      ? data.posts.map(p => postCardHTML(p, sec)).join('')
      : '<div class="empty"><div class="icon">◈</div><p>No reports in this section yet.</p></div>';
    document.title = `${sec.name} · ${state.site.name}`;

    APP.innerHTML = `
      <a class="back-link" href="/">← All allies</a>
      <div class="hero" style="border-bottom-color:${esc(sec.color || 'var(--border)')}">
        <span class="mark-big" aria-hidden="true">◈</span>
        <div class="tagline">ALLY SECTION</div>
        <h1>${esc(sec.name)}</h1>
        <p>${esc(sec.desc)}</p>
      </div>
      <h2 class="section-title" style="margin-bottom:18px">
        Intel Reports <span class="count">${data.posts.length}</span>
      </h2>
      <div class="posts-grid">${cards}</div>`;
  } catch (e) {
    APP.innerHTML = `<div class="empty"><div class="icon">⚠</div><p>${esc(e.message)}</p></div>`;
  }
}

function postCardHTML(p, sec) {
  return `
    <article class="card">
      <a href="/s/${esc(p.section)}/${esc(p.slug)}" class="card-cover" style="display:block">
        ${p.cover
          ? `<img src="${esc(p.cover)}" alt="" loading="lazy">`
          : `<div class="placeholder" style="color:${esc(sec.color || '#4fd1c5')}">◈</div>`}
        ${p.featured ? '<span class="card-featured">Featured</span>' : ''}
      </a>
      <div class="card-body">
        <div class="card-meta">
          <span>${esc(fmtDate(p.date))}</span>
          ${p.author ? `<span class="dot"></span><span>${esc(p.author)}</span>` : ''}
        </div>
        <h3 class="card-title">
          <a href="/s/${esc(p.section)}/${esc(p.slug)}">${esc(p.title)}</a>
        </h3>
        <p class="card-excerpt">${esc(p.excerpt)}</p>
        <div class="card-footer">
          <div class="card-tags">
            ${(p.tags || []).slice(0, 3).map(t => `<span>${esc(t)}</span>`).join('')}
          </div>
        </div>
      </div>
    </article>`;
}

/* ══════════════════════════════════════════════════
   POST
   ══════════════════════════════════════════════════ */
async function renderPost(sectionId, slug) {
  APP.innerHTML = '<div class="empty"><div class="icon">◈</div><p>Loading…</p></div>';
  try {
    if (!state.loaded) await loadSite();
    const data = await api(
      `/api/alliance/sections/${encodeURIComponent(sectionId)}/posts/${encodeURIComponent(slug)}`);
    const p = data.post;
    const sec = data.section;
    document.title = `${p.title} · ${state.site.name}`;

    APP.innerHTML = `
      <a class="back-link" href="/s/${esc(sectionId)}">← ${esc(sec.name)}</a>
      <article>
        <header class="post-header">
          <div class="post-meta">
            <span class="section-badge" style="color:${esc(sec.color || '#4fd1c5')}">${esc(sec.name)}</span>
            <span>${esc(fmtDate(p.date))}</span>
            ${p.author ? `<span>by ${esc(p.author)}</span>` : ''}
          </div>
          <h1>${esc(p.title)}</h1>
        </header>
        ${p.cover ? `<div class="post-cover"><img src="${esc(p.cover)}" alt=""></div>` : ''}
        <div class="prose">${p.content_html || '<p><em>Empty report.</em></p>'}</div>
      </article>`;
  } catch (e) {
    APP.innerHTML = `<div class="empty"><div class="icon">⚠</div><p>${esc(e.message)}</p></div>`;
  }
}

/* ══════════════════════════════════════════════════
   Admin login
   ══════════════════════════════════════════════════ */
function renderAdmin() {
  if (state.admin.token) {
    history.replaceState(null, '', '/admin/panel');
    return renderAdminPanel();
  }
  document.title = 'Admin · ' + (state.site?.name || 'Alliance');
  APP.innerHTML = `
    <div class="login-card">
      <h1>Admin Login</h1>
      <p>Sign in to manage your ally section.</p>
      <form id="loginForm">
        <div class="field">
          <label for="u">Username</label>
          <input id="u" autocomplete="username" required>
        </div>
        <div class="field">
          <label for="p">Password</label>
          <input id="p" type="password" autocomplete="current-password" required>
        </div>
        <button class="btn btn-block" type="submit" id="loginBtn">Sign in</button>
      </form>
    </div>`;
  $('loginForm').addEventListener('submit', async e => {
    e.preventDefault();
    const btn = $('loginBtn');
    const orig = btn.textContent;
    btn.disabled = true; btn.textContent = '…';
    try {
      const r = await api('/api/alliance/login', {
        method: 'POST',
        body: { username: $('u').value.trim(), password: $('p').value },
      });
      saveAdmin({
        token: r.token,
        section_id: r.section_id,
        section_name: r.section_name,
        username: r.username,
      });
      history.replaceState(null, '', '/admin/panel');
      renderAdminPanel();
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      btn.disabled = false; btn.textContent = orig;
    }
  });
}

/* ══════════════════════════════════════════════════
   Admin panel
   ══════════════════════════════════════════════════ */
async function renderAdminPanel() {
  if (!state.admin.token) {
    history.replaceState(null, '', '/admin');
    return renderAdmin();
  }
  APP.innerHTML = '<div class="empty"><div class="icon">◈</div><p>Loading…</p></div>';
  try {
    const data = await api('/api/alliance/admin/posts');
    const section = data.section;
    state.sectionMap[section.id] = section;
    document.title = `${section.name} · Admin`;

    const avatarUrl = section.image || '';

    APP.innerHTML = `
      <div class="admin-wrap">
        <div class="admin-header">
          <div>
            <h1>${esc(section.name)}</h1>
            <div class="admin-subtitle">
              Signed in as <strong>${esc(state.admin.username)}</strong>
              · You can only manage <strong>${esc(section.name)}</strong>'s reports.
            </div>
          </div>
          <span class="badge">Admin</span>
          <div class="spacer"></div>
          <button class="btn btn-secondary btn-sm" id="logoutBtn">Logout</button>
        </div>

        <div class="avatar-panel">
          <div class="preview" id="avatarPreview">
            ${avatarUrl
              ? `<img src="${esc(avatarUrl)}" alt="">`
              : `<span class="ph">◈</span>`}
          </div>
          <div class="info">
            <label for="avatarInput">Section emblem URL</label>
            <input id="avatarInput" placeholder="https://…" value="${esc(avatarUrl)}">
          </div>
          <button class="btn btn-secondary btn-sm" id="saveAvatarBtn">Save</button>
        </div>

        <div id="editorSlot"></div>

        <h2 class="section-title" style="margin-top:26px;margin-bottom:14px">
          Your Reports <span class="count">${data.posts.length}</span>
        </h2>
        <div class="admin-list" id="adminList">
          ${data.posts.length
            ? data.posts.map(adminItemHTML).join('')
            : '<div class="empty"><div class="icon">◈</div><p>No reports yet.</p></div>'}
        </div>
      </div>`;

    $('logoutBtn').addEventListener('click', async () => {
      try { await api('/api/alliance/logout', { method: 'POST', body: { token: state.admin.token } }); }
      catch {}
      saveAdmin({ token: null, section_id: null, username: null, section_name: null });
      toast('Logged out', 'ok');
      history.replaceState(null, '', '/admin');
      renderAdmin();
    });

    $('saveAvatarBtn').addEventListener('click', async () => {
      const url = $('avatarInput').value.trim();
      try {
        const r = await api('/api/alliance/admin/avatar', {
          method: 'POST',
          body: { avatar: url },
        });
        state.sectionMap[r.section.id] = r.section;
        $('avatarPreview').innerHTML = url
          ? `<img src="${esc(url)}" alt="">`
          : `<span class="ph">◈</span>`;
        toast('Emblem updated', 'ok');
      } catch (e) {
        toast(e.message, 'error');
      }
    });

    wireAdminList(data.posts, section.id);
    showEditor(null, section);
  } catch (e) {
    if (e.status === 401) {
      saveAdmin({ token: null, section_id: null, username: null, section_name: null });
      toast('Session expired', 'error');
      history.replaceState(null, '', '/admin');
      return renderAdmin();
    }
    APP.innerHTML = `<div class="empty"><div class="icon">⚠</div><p>${esc(e.message)}</p></div>`;
  }
}

function adminItemHTML(p) {
  return `
    <div class="admin-item" data-id="${esc(p.id)}" data-slug="${esc(p.slug)}">
      <div class="info">
        <div class="title">${esc(p.title)}</div>
        <div class="meta">${esc(fmtDate(p.date))} · /${esc(p.slug)}${p.featured ? ' · ★' : ''}</div>
      </div>
      <div class="actions">
        <button class="btn btn-secondary btn-sm" data-act="edit">Edit</button>
        <button class="btn btn-danger btn-sm" data-act="delete">Delete</button>
      </div>
    </div>`;
}

function wireAdminList(posts, sectionId) {
  const list = $('adminList');
  if (!list) return;
  list.querySelectorAll('.admin-item').forEach(item => {
    const id = item.dataset.id;
    const slug = item.dataset.slug;
    item.querySelector('[data-act="edit"]').addEventListener('click', async () => {
      try {
        const full = await api(
          `/api/alliance/sections/${encodeURIComponent(sectionId)}/posts/${encodeURIComponent(slug)}`);
        showEditor(full.post, state.sectionMap[sectionId]);
      } catch (e) { toast(e.message, 'error'); }
    });
    item.querySelector('[data-act="delete"]').addEventListener('click', async () => {
      if (!confirm('Delete this report?')) return;
      try {
        await api(`/api/alliance/admin/posts/${id}`, { method: 'DELETE' });
        toast('Deleted', 'ok');
        renderAdminPanel();
      } catch (e) { toast(e.message, 'error'); }
    });
  });
}

/* ══════════════════════════════════════════════════
   Editor
   ══════════════════════════════════════════════════ */
function showEditor(post, section) {
  const slot = $('editorSlot');
  if (!slot) return;
  const editing = !!post;
  const p = post || {};
  const tagsValue = (p.tags || []).join(', ');
  const dateValue = p.date ? toLocalInput(p.date) : '';

  slot.innerHTML = `
    <div class="editor">
      <h3>${editing ? 'Edit report' : 'New report'}</h3>
      <form id="editorForm" data-editing="${editing ? '1' : '0'}" data-id="${esc(p.id || '')}">
        <div class="row-2">
          <div class="field">
            <label>Title *</label>
            <input name="title" required maxlength="200" value="${esc(p.title || '')}">
          </div>
          <div class="field">
            <label>Author</label>
            <input name="author" maxlength="60" value="${esc(p.author || '')}">
          </div>
        </div>
        <div class="field">
          <label>Cover image URL</label>
          <input name="cover" placeholder="https://…" value="${esc(p.cover || '')}">
        </div>
        <div class="row-2">
          <div class="field">
            <label>Tags (comma separated)</label>
            <input name="tags" value="${esc(tagsValue)}">
          </div>
          <div class="field">
            <label>Date</label>
            <input name="date" type="datetime-local" value="${esc(dateValue)}">
          </div>
        </div>
        <div class="field">
          <label>Excerpt (summary)</label>
          <textarea name="excerpt" maxlength="300" rows="2">${esc(p.excerpt || '')}</textarea>
        </div>
        <div class="field">
          <label>Content (markdown)</label>
          <textarea name="content" class="content" maxlength="50000">${esc(p.content || '')}</textarea>
        </div>
        <div class="checkbox-row">
          <input type="checkbox" name="featured" id="feat" ${p.featured ? 'checked' : ''}>
          <label for="feat" style="margin:0;cursor:pointer">Featured</label>
        </div>
        <div class="editor-actions">
          <button class="btn" type="submit" id="saveBtn">${editing ? 'Save changes' : 'Publish'}</button>
          ${editing ? '<button class="btn btn-secondary" type="button" id="cancelEdit">Cancel</button>' : ''}
        </div>
      </form>
    </div>`;

  if (editing) {
    $('cancelEdit').addEventListener('click', () => showEditor(null, section));
  }

  $('editorForm').addEventListener('submit', async e => {
    e.preventDefault();
    const form = e.target;
    const fd = new FormData(form);
    const dateRaw = (fd.get('date') || '').toString();
    const payload = {
      title: (fd.get('title') || '').toString().trim(),
      author: (fd.get('author') || '').toString().trim(),
      cover: (fd.get('cover') || '').toString().trim(),
      tags: (fd.get('tags') || '').toString().split(',').map(t => t.trim()).filter(Boolean),
      excerpt: (fd.get('excerpt') || '').toString().trim(),
      content: (fd.get('content') || '').toString(),
      featured: form.querySelector('[name=featured]').checked,
      date: dateRaw ? new Date(dateRaw).toISOString() : new Date().toISOString(),
    };
    const btn = $('saveBtn');
    const orig = btn.textContent;
    btn.disabled = true; btn.textContent = '…';
    try {
      if (editing) {
        await api(`/api/alliance/admin/posts/${form.dataset.id}`,
          { method: 'PUT', body: payload });
      } else {
        await api('/api/alliance/admin/posts', { method: 'POST', body: payload });
      }
      toast(editing ? 'Saved' : 'Published', 'ok');
      renderAdminPanel();
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      btn.disabled = false; btn.textContent = orig;
    }
  });
}

/* ══════════════════════════════════════════════════
   Helpers
   ══════════════════════════════════════════════════ */
function fmtDate(iso) {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    if (isNaN(d)) return iso;
    return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
  } catch { return iso; }
}
function toLocalInput(iso) {
  try {
    const d = new Date(iso);
    if (isNaN(d)) return '';
    const pad = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  } catch { return ''; }
}
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function render404() {
  APP.innerHTML = `<div class="empty"><div class="icon">◈</div><p>404 — Page not found.</p></div>`;
}

/* ══════════════════════════════════════════════════
   Boot
   ══════════════════════════════════════════════════ */
document.addEventListener('DOMContentLoaded', () => {
  applyTheme();
  wireTheme();
  loadSite().then(route).catch(() => route());

  window.addEventListener('popstate', route);

  document.body.addEventListener('click', e => {
    const a = e.target.closest('a[href]');
    if (!a) return;
    const href = a.getAttribute('href');
    if (!href || !href.startsWith('/') || a.target || href.startsWith('//')) return;
    if (href.startsWith('/data/')) return;   // let browser hit /data/<uuid>
    e.preventDefault();
    history.pushState(null, '', href);
    route();
  });
});
