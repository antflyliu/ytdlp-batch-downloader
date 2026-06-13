// RSS Catalog management module
// API helpers
const RSS_API = {
  sources() { return '/api/rss/catalog/sources'; },
  sourceFile() { return '/api/rss/catalog/sources/file'; },
  sourceSync(key) { return `/api/rss/catalog/sources/${encodeURIComponent(key)}/sync`; },
  sourceDel(key) { return `/api/rss/catalog/sources/${encodeURIComponent(key)}`; },
};

async function rssApiJson(url, method = 'GET', body = null) {
  const opts = { method, headers: { 'Accept': 'application/json' } };
  if (body) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
  const res = await fetch(url, opts);
  if (!res.ok) { const err = await res.json().catch(() => ({ error: res.statusText })); throw new Error(err.error || res.statusText); }
  return res.json();
}

// Tab switching
function switchRssTab(tab) {
  document.querySelectorAll('.tabs-mini__btn').forEach(b => b.classList.toggle('tabs-mini__btn--active', b.dataset.tab === tab));
  document.querySelectorAll('.rss-tab-content').forEach(el => el.classList.toggle('rss-tab-content--active', el.id === 'rss-add-' + tab));
}
window.switchRssTab = switchRssTab;

// File selection handler
const _rssFileData = { name: '', content: '' };
function onRssFileSelected(event) {
  const file = event.target.files[0];
  if (!file) return;
  const display = document.getElementById('rss-file-name');
  if (display) display.textContent = file.name;
  const reader = new FileReader();
  reader.onload = (e) => {
    _rssFileData.name = file.name;
    _rssFileData.content = e.target.result;
  };
  reader.readAsText(file);
}
window.onRssFileSelected = onRssFileSelected;

// Add source from URL
async function addRssSourceFromUrl() {
  const name = document.getElementById('rss-source-name-url').value.trim();
  const feedsUrl = document.getElementById('rss-source-feeds-url').value.trim();
  if (!name || !feedsUrl) { alert(I18n.t('rssCatalog.urlRequired')); return; }
  try {
    await rssApiJson(RSS_API.sources(), 'POST', { name, feeds_url: feedsUrl });
    document.getElementById('rss-source-name-url').value = '';
    document.getElementById('rss-source-feeds-url').value = '';
    refreshRssSources();
  } catch (e) { alert(I18n.t('rssCatalog.addFailed') + ': ' + e.message); }
}
window.addRssSourceFromUrl = addRssSourceFromUrl;

// Add source from file upload
async function addRssSourceFromFile() {
  const name = document.getElementById('rss-source-name-file').value.trim();
  if (!name) { alert(I18n.t('rssCatalog.nameRequired')); return; }
  if (!_rssFileData.content) { alert(I18n.t('rssCatalog.opmlFileRequired')); return; }
  try {
    // Try multipart upload first
    const formData = new FormData();
    formData.append('name', name);
    formData.append('opml_file', new Blob([_rssFileData.content], { type: 'text/xml' }), _rssFileData.name || 'source.opml');
    const res = await fetch(RSS_API.sourceFile(), { method: 'POST', body: formData });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: res.statusText }));
      throw new Error(err.error || res.statusText);
    }
    document.getElementById('rss-source-name-file').value = '';
    document.getElementById('rss-file-name').textContent = '';
    document.getElementById('rss-file-input').value = '';
    _rssFileData.name = '';
    _rssFileData.content = '';
    refreshRssSources();
  } catch (e) { alert(I18n.t('rssCatalog.addFailed') + ': ' + e.message); }
}
window.addRssSourceFromFile = addRssSourceFromFile;

// Delete source
async function deleteRssSource(sourceKey) {
  if (!confirm(I18n.t('rssCatalog.deleteConfirm'))) return;
  try {
    await rssApiJson(RSS_API.sourceDel(sourceKey), 'DELETE');
    refreshRssSources();
  } catch (e) { alert(I18n.t('rssCatalog.deleteFailed') + ': ' + e.message); }
}
window.deleteRssSource = deleteRssSource;

// Sync source
async function syncRssSource(sourceKey) {
  try {
    const data = await rssApiJson(RSS_API.sourceSync(sourceKey), 'POST');
    refreshRssSources();
  } catch (e) { alert(I18n.t('rssCatalog.syncFailed') + ': ' + e.message); }
}
window.syncRssSource = syncRssSource;

// Refresh source list
async function refreshRssSources() {
  const container = document.getElementById('rss-source-list');
  if (!container) return;
  container.innerHTML = '<div class="loading-spinner">' + I18n.t('rssCatalog.loading') + '</div>';
  try {
    const data = await rssApiJson(RSS_API.sources());
    const sources = data.sources || [];
    if (sources.length === 0) {
      container.innerHTML = '<div class="empty-state">' + I18n.t('rssCatalog.noSources') + '</div>';
      return;
    }
    let html = '<table class="table"><thead><tr><th>' + I18n.t('rssCatalog.colName') + '</th><th>' + I18n.t('rssCatalog.colType') + '</th><th>' + I18n.t('rssCatalog.colFeeds') + '</th><th>' + I18n.t('rssCatalog.colSyncTime') + '</th><th>' + I18n.t('rssCatalog.colStatus') + '</th><th>' + I18n.t('rssCatalog.colActions') + '</th></tr></thead><tbody>';
    for (const s of sources) {
      const syncTime = s.last_synced_at ? new Date(s.last_synced_at).toLocaleString() : '-';
      const status = s.last_sync_status === 'ok' ? '<span class="badge badge--success">' + I18n.t('rssCatalog.statusOk') + '</span>'
        : s.last_sync_status === 'error' ? '<span class="badge badge--danger" title="' + (s.last_sync_error || '') + '">' + I18n.t('rssCatalog.statusError') + '</span>'
        : '<span class="badge badge--muted">' + I18n.t('rssCatalog.statusPending') + '</span>';
      const type = s.feeds_url ? I18n.t('rssCatalog.typeUrl') : s.opml_content ? I18n.t('rssCatalog.typeFile') : '-';
      const key = encodeURIComponent(s.source_key);
      html += `<tr>
        <td><strong>${s.name || s.source_key}</strong></td>
        <td>${type}</td>
        <td>${s.feed_total || 0}</td>
        <td>${syncTime}</td>
        <td>${status}</td>
        <td class="actions-cell">
          <button class="btn btn--sm btn--outline" onclick="syncRssSource('${key}')">' + I18n.t('rssCatalog.btnSync') + '</button>
          <button class="btn btn--sm btn--danger-soft" onclick="deleteRssSource('${key}')">' + I18n.t('rssCatalog.btnDelete') + '</button>
        </td>
      </tr>`;
    }
    html += '</tbody></table>';
    container.innerHTML = html;
  } catch (e) {
    container.innerHTML = '<div class="error-state">' + I18n.t('rssCatalog.loadFailed') + ': ' + e.message + '</div>';
  }
}
window.refreshRssSources = refreshRssSources;

// Page lifecycle
function init_rss_settings_page() {
  refreshRssSources();
}
window.init_rss_settings_page = init_rss_settings_page;

function destroy_rss_settings_page() {
  // cleanup
}
window.destroy_rss_settings_page = destroy_rss_settings_page;
