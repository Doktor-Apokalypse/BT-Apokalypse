const state = { torrents: [], status: {}, settings: {}, filter: "all", search: "", selected: new Set(), detailId: null, detailTab: "files", addTab: "magnet", folderTarget: null, folderParent: null };
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"})[char]);
}
function bytes(value, decimals = 1) {
  const number = Number(value || 0); if (!number) return "0 B";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"]; const unit = Math.min(Math.floor(Math.log(number) / Math.log(1024)), units.length - 1);
  return `${(number / 1024 ** unit).toFixed(unit ? decimals : 0)} ${units[unit]}`;
}
const rate = value => `${bytes(value)}/s`;
function eta(value) { if (value == null || value > 359999) return "∞"; if (value < 60) return `${value}s`; if (value < 3600) return `${Math.ceil(value/60)}m`; if (value < 86400) return `${Math.floor(value/3600)}h ${Math.ceil(value%3600/60)}m`; return `${Math.ceil(value/86400)}d`; }
async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let message = response.statusText;
    try { const body = await response.json(); message = body.detail || message; } catch (_) {}
    throw new Error(message);
  }
  return response.status === 204 ? null : response.json();
}
function toast(message, error = false) {
  const item = document.createElement("div"); item.className = `toast${error ? " error" : ""}`; item.textContent = message;
  $("#toast-stack").append(item); setTimeout(() => item.remove(), 3500);
}
function show(dialog) { dialog.showModal(); }
function closeDialog(element) { element.closest("dialog")?.close(); }

async function refresh() {
  try {
    const [torrents, status] = await Promise.all([api("/api/torrents"), api("/api/status")]);
    state.torrents = torrents; state.status = status; render();
    if (state.detailId && $("#details-dialog").open) updateDetailHeader();
  } catch (error) { $("#network-label").textContent = "Engine offline"; $("#network-light").classList.remove("online"); }
}
function matchesFilter(torrent) {
  if (state.filter === "all") return true;
  if (state.filter === "completed") return ["completed", "seeding"].includes(torrent.state);
  return torrent.state === state.filter;
}
function render() {
  $("#global-down").textContent = rate(state.status.download_rate); $("#global-up").textContent = rate(state.status.upload_rate);
  $("#dht-count").textContent = state.status.dht_nodes || 0; $("#connection-count").textContent = state.status.connections || 0;
  $("#listen-port").textContent = state.status.listen_port || "—"; $("#network-label").textContent = state.status.listening ? "Network active" : "Not listening";
  $("#network-light").classList.toggle("online", !!state.status.listening); $("#footer-version").textContent = `libtorrent ${state.status.libtorrent_version || ""}`;
  const counts = {all: state.torrents.length, downloading:0, seeding:0, completed:0, paused:0, error:0};
  state.torrents.forEach(t => { if (counts[t.state] !== undefined) counts[t.state]++; if (["completed","seeding"].includes(t.state)) counts.completed++; });
  Object.entries(counts).forEach(([key,value]) => { const node = $(`#count-${key}`); if (node) node.textContent = value; });
  const query = state.search.toLowerCase();
  const visible = state.torrents.filter(t => matchesFilter(t) && t.name.toLowerCase().includes(query));
  $("#torrent-list").innerHTML = visible.map(torrentRow).join("");
  $("#empty-state").classList.toggle("show", visible.length === 0); $(".torrent-table").style.display = visible.length ? "table" : "none";
  $("#select-all").checked = visible.length > 0 && visible.every(t => state.selected.has(t.id));
}
function torrentRow(t) {
  const selected = state.selected.has(t.id); const sub = t.error || t.state.replaceAll("_", " ");
  return `<tr data-id="${escapeHtml(t.id)}" class="state-${escapeHtml(t.state)}${selected ? " selected" : ""}">
    <td class="check"><input type="checkbox" ${selected ? "checked" : ""} aria-label="Select ${escapeHtml(t.name)}"></td>
    <td><div class="torrent-name"><span class="file-icon">BT</span><div><strong title="${escapeHtml(t.name)}">${escapeHtml(t.name)}</strong><small>${escapeHtml(sub)}</small></div></div></td>
    <td>${bytes(t.total_size)}</td><td><div class="progress-cell"><div class="progress-track"><i style="width:${t.progress}%"></i></div><span>${Number(t.progress).toFixed(1)}%</span></div></td>
    <td class="rate-down">${rate(t.download_rate)}</td><td class="rate-up">${rate(t.upload_rate)}</td><td>${t.seeds} / ${t.peers}</td><td>${eta(t.eta)}</td>
    <td><button class="row-menu" aria-label="Open details">•••</button></td></tr>`;
}

async function actionSelected(action) {
  if (!state.selected.size) return toast("Select at least one torrent", true);
  try { await Promise.all([...state.selected].map(id => api(`/api/torrents/${id}/action`, {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action})}))); await refresh(); }
  catch (error) { toast(error.message, true); }
}
async function removeSelected() {
  if (!state.selected.size) return toast("Select at least one torrent", true);
  if (!confirm("Remove the selected torrents from the client?")) return;
  const deleteFiles = confirm("Also delete their downloaded files?\n\nCancel keeps the downloaded data.");
  try { await Promise.all([...state.selected].map(id => api(`/api/torrents/${id}?delete_files=${deleteFiles}`, {method:"DELETE"}))); state.selected.clear(); await refresh(); }
  catch (error) { toast(error.message, true); }
}

async function openAdd() {
  try { state.settings = await api("/api/settings"); $("#add-save-path").value = state.settings.download_dir; $("#add-completed-path").value = state.settings.completed_dir || ""; } catch (_) {}
  show($("#add-dialog"));
}
async function submitAdd(event) {
  event.preventDefault(); const button = $("#add-submit"); button.disabled = true; button.textContent = "Adding…";
  try {
    const common = {save_path: $("#add-save-path").value, completed_path: $("#add-completed-path").value || null, sequential: $("#add-sequential").checked, paused: $("#add-paused").checked};
    if (state.addTab === "magnet") {
      await api("/api/torrents/magnet", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({...common,magnet:$("#magnet-input").value.trim()})});
    } else {
      const file = $("#torrent-file").files[0]; if (!file) throw new Error("Choose a .torrent file");
      const form = new FormData(); form.append("torrent", file); Object.entries(common).forEach(([key,value]) => { if (value != null) form.append(key,String(value)); });
      await api("/api/torrents/file", {method:"POST",body:form});
    }
    $("#add-dialog").close(); $("#add-form").reset(); toast("Torrent added to the queue"); await refresh();
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; button.textContent = "Add torrent"; }
}

async function openDetails(id) { state.detailId = id; state.detailTab = "files"; $$("[data-detail-tab]").forEach(t => t.classList.toggle("active", t.dataset.detailTab === "files")); updateDetailHeader(); show($("#details-dialog")); await loadDetail(); }
function updateDetailHeader() {
  const torrent = state.torrents.find(t => t.id === state.detailId); if (!torrent) return;
  $("#details-name").textContent = torrent.name; $("#details-state").textContent = torrent.state.toUpperCase();
  $("#detail-summary").innerHTML = [
    ["SIZE",bytes(torrent.total_size)],["DOWN",rate(torrent.download_rate)],["UP",rate(torrent.upload_rate)],["RATIO",torrent.ratio],["PEERS",`${torrent.seeds} seeds · ${torrent.peers} peers`]
  ].map(([label,value]) => `<div><small>${label}</small><strong>${value}</strong></div>`).join("");
}
async function loadDetail() {
  const content = $("#detail-content"); content.innerHTML = '<p class="help">Loading…</p>';
  try {
    if (state.detailTab === "files") {
      const files = await api(`/api/torrents/${state.detailId}/files`);
      content.innerHTML = files.length ? `<table class="mini-table"><thead><tr><th>File</th><th>Size</th><th>Progress</th><th>Priority</th></tr></thead><tbody>${files.map(f => `<tr><td title="${escapeHtml(f.path)}">${escapeHtml(f.path)}</td><td>${bytes(f.size)}</td><td>${f.progress}%</td><td><select class="file-priority" data-index="${f.index}"><option value="0" ${f.priority===0?'selected':''}>Skip</option><option value="1" ${f.priority===1?'selected':''}>Low</option><option value="4" ${![0,1,7].includes(f.priority)?'selected':''}>Normal</option><option value="7" ${f.priority===7?'selected':''}>High</option></select></td></tr>`).join("")}</tbody></table>` : '<p class="help">Waiting for magnet metadata…</p>';
    } else if (state.detailTab === "peers") {
      const peers = await api(`/api/torrents/${state.detailId}/peers`);
      content.innerHTML = peers.length ? `<table class="mini-table"><thead><tr><th>Address</th><th>Client</th><th>Progress</th><th>Down</th><th>Up</th><th></th></tr></thead><tbody>${peers.map(p => `<tr><td>${escapeHtml(p.ip)}:${p.port}</td><td>${escapeHtml(p.client || 'Unknown')}</td><td>${p.progress}%</td><td>${rate(p.download_rate)}</td><td>${rate(p.upload_rate)}</td><td><button class="secondary ban-peer" data-ip="${escapeHtml(p.ip)}">Ban</button></td></tr>`).join("")}</tbody></table>` : '<p class="help">No connected peers.</p>';
    } else if (state.detailTab === "trackers") {
      const trackers = await api(`/api/torrents/${state.detailId}/trackers`);
      content.innerHTML = `<form id="tracker-form" class="inline-form"><input id="tracker-url" placeholder="udp://tracker.example:80/announce"><button class="secondary">Add</button></form><table class="mini-table"><thead><tr><th>Tracker</th><th>Tier</th><th>Status</th></tr></thead><tbody>${trackers.map(t => `<tr><td>${escapeHtml(t.url)}</td><td>${t.tier}</td><td>${t.verified?'Verified':'Waiting'}</td></tr>`).join("")}</tbody></table>`;
    } else {
      const torrent = state.torrents.find(t => t.id === state.detailId);
      content.innerHTML = `<div class="detail-options"><section><h3>Download behavior</h3><label class="checkline"><input id="detail-sequential" type="checkbox" ${torrent.sequential?'checked':''}> Download pieces sequentially</label><label class="checkline"><input id="detail-move" type="checkbox" ${torrent.move_completed?'checked':''}> Move after completion</label><label>Completed folder<input id="detail-completed" value="${escapeHtml(torrent.completed_path)}"></label><button id="detail-save" class="primary">Save options</button></section><section><h3>Maintenance</h3><p class="help">Force a data verification or ask trackers and DHT for peers immediately.</p><div class="toggle-row"><button class="secondary detail-action" data-action="recheck">Recheck files</button><button class="secondary detail-action" data-action="reannounce">Reannounce</button></div><p class="help">Current data folder<br><strong>${escapeHtml(torrent.save_path)}</strong></p></section></div>`;
    }
  } catch (error) { content.innerHTML = `<p class="help">${escapeHtml(error.message)}</p>`; }
}

async function openSettings() {
  try {
    state.settings = await api("/api/settings"); const form = $("#settings-form");
    Object.entries(state.settings).forEach(([key,value]) => { const field = form.elements.namedItem(key); if (!field) return; if (field.type === "checkbox") field.checked = !!value; else field.value = String(value); });
    show($("#settings-dialog"));
  } catch (error) { toast(error.message,true); }
}
async function saveSettings(event) {
  event.preventDefault(); const form = new FormData(event.target); const payload = {};
  ["download_dir","completed_dir"].forEach(key => payload[key] = form.get(key));
  ["listen_port","max_connections","download_limit_kib","upload_limit_kib"].forEach(key => payload[key] = Number(form.get(key)));
  ["move_completed","enable_dht","enable_pex","enable_lsd","enable_upnp","enable_natpmp"].forEach(key => payload[key] = event.target.elements.namedItem(key).checked);
  payload.auto_start = form.get("auto_start") === "true";
  try { await api("/api/settings",{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)}); $("#settings-dialog").close(); toast("Settings saved"); await refresh(); }
  catch(error){ toast(error.message,true); }
}

async function openBlocklist() { show($("#blocklist-dialog")); await loadBlocklist(); }
async function loadBlocklist() {
  try { const data = await api("/api/blocklist"); $("#block-total").textContent = data.count; $("#block-count").textContent = data.count; $("#block-rules").innerHTML = data.rules.slice().reverse().map(r => `<div class="rule"><span>${escapeHtml(r.label)}</span><span>${escapeHtml(r.first)}</span><span>${escapeHtml(r.last)}</span></div>`).join(""); }
  catch(error){ toast(error.message,true); }
}

async function browse(targetId) { state.folderTarget = targetId; const current = targetId === "settings-download" ? $("#settings-form [name=download_dir]").value : $(`#${targetId}`).value; show($("#folder-dialog")); await loadFolder(current); }
async function loadFolder(path) {
  try { const data = await api(`/api/directories${path ? `?path=${encodeURIComponent(path)}` : ""}`); state.folderParent = data.parent; $("#folder-current").value = data.path; $("#folder-roots").innerHTML = data.roots.map(root => `<button data-path="${escapeHtml(root)}">${escapeHtml(root)}</button>`).join(""); $("#folder-list").innerHTML = data.directories.map(dir => `<button class="folder-item" data-path="${escapeHtml(dir.path)}">${escapeHtml(dir.name)}</button>`).join(""); }
  catch(error){ toast(error.message,true); }
}
function chooseFolder() { const path = $("#folder-current").value; const target = state.folderTarget === "settings-download" ? $("#settings-form [name=download_dir]") : $(`#${state.folderTarget}`); target.value = path; $("#folder-dialog").close(); }

document.addEventListener("click", async event => {
  const close = event.target.closest("[data-close]"); if (close) return closeDialog(close);
  const filter = event.target.closest(".filter"); if (filter) { state.filter = filter.dataset.filter; $$(".filter").forEach(f => f.classList.toggle("active",f===filter)); $("#view-title").textContent = filter.textContent.replace(/\d+$/,"").trim(); return render(); }
  const browseButton = event.target.closest("[data-browse]"); if (browseButton) return browse(browseButton.dataset.browse);
  const row = event.target.closest("#torrent-list tr"); if (row) { if (event.target.matches('input[type="checkbox"]')) { event.target.checked ? state.selected.add(row.dataset.id) : state.selected.delete(row.dataset.id); return render(); } return openDetails(row.dataset.id); }
  const detailTab = event.target.closest("[data-detail-tab]"); if (detailTab) { state.detailTab = detailTab.dataset.detailTab; $$("[data-detail-tab]").forEach(t => t.classList.toggle("active",t===detailTab)); return loadDetail(); }
  const addTab = event.target.closest("[data-add-tab]"); if (addTab) { state.addTab = addTab.dataset.addTab; $$("[data-add-tab]").forEach(t => t.classList.toggle("active",t===addTab)); $("#magnet-panel").classList.toggle("hidden",state.addTab!=="magnet"); $("#file-panel").classList.toggle("hidden",state.addTab!=="file"); }
  const detailAction = event.target.closest(".detail-action"); if (detailAction) { try { await api(`/api/torrents/${state.detailId}/action`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action:detailAction.dataset.action})}); toast("Action requested"); } catch(error){toast(error.message,true);} }
  const banPeer = event.target.closest(".ban-peer"); if (banPeer) { try { await api("/api/blocklist/ban",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({ip:banPeer.dataset.ip})}); toast(`${banPeer.dataset.ip} banned`); await loadDetail(); } catch(error){toast(error.message,true);} }
});

$("#add-open").onclick = $("#empty-add").onclick = openAdd; $("#add-form").onsubmit = submitAdd; $("#settings-open").onclick = openSettings; $("#settings-form").onsubmit = saveSettings; $("#blocklist-open").onclick = openBlocklist;
$("#search").oninput = event => { state.search = event.target.value; render(); }; $("#resume-selected").onclick = () => actionSelected("resume"); $("#pause-selected").onclick = () => actionSelected("pause"); $("#remove-selected").onclick = removeSelected;
$("#select-all").onchange = event => { state.torrents.filter(matchesFilter).forEach(t => event.target.checked ? state.selected.add(t.id) : state.selected.delete(t.id)); render(); };
$("#torrent-list").addEventListener("dblclick", event => { const row=event.target.closest("tr"); if(row) api(`/api/torrents/${row.dataset.id}/action`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action:"resume"})}).then(refresh); });
$("#detail-content").addEventListener("change", async event => { if (!event.target.matches(".file-priority")) return; try { await api(`/api/torrents/${state.detailId}/files`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({priorities:{[event.target.dataset.index]:Number(event.target.value)}})}); } catch(error){toast(error.message,true);} });
$("#detail-content").addEventListener("submit", async event => { if (event.target.id !== "tracker-form") return; event.preventDefault(); try { await api(`/api/torrents/${state.detailId}/trackers`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({url:$("#tracker-url").value})}); await loadDetail(); } catch(error){toast(error.message,true);} });
$("#detail-content").addEventListener("click", async event => { if (event.target.id !== "detail-save") return; try { await api(`/api/torrents/${state.detailId}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({sequential:$("#detail-sequential").checked,move_completed:$("#detail-move").checked,completed_path:$("#detail-completed").value})}); toast("Torrent options saved"); await refresh(); } catch(error){toast(error.message,true);} });
$("#ban-form").onsubmit = async event => { event.preventDefault(); try { await api("/api/blocklist/ban",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({ip:$("#ban-ip").value})}); event.target.reset(); await loadBlocklist(); } catch(error){toast(error.message,true);} };
$("#block-url-form").onsubmit = async event => { event.preventDefault(); try { const result=await api("/api/blocklist/url",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({url:$("#block-url").value})}); toast(`Imported ${result.added} rules`); event.target.reset(); await loadBlocklist(); } catch(error){toast(error.message,true);} };
$("#block-file").onchange = async event => { const form=new FormData(); form.append("blocklist",event.target.files[0]); try { const result=await api("/api/blocklist/file",{method:"POST",body:form}); toast(`Imported ${result.added} rules`); await loadBlocklist(); } catch(error){toast(error.message,true);} };
$("#clear-blocklist").onclick = async () => { if(!confirm("Clear every IP block rule?")) return; await api("/api/blocklist",{method:"DELETE"}); await loadBlocklist(); };
$("#folder-up").onclick = () => state.folderParent && loadFolder(state.folderParent); $("#folder-current").onchange = event => loadFolder(event.target.value); $("#folder-select").onclick = chooseFolder;
$("#folder-list").onclick = event => { const item=event.target.closest("[data-path]"); if(item) loadFolder(item.dataset.path); }; $("#folder-roots").onclick = event => { const item=event.target.closest("[data-path]"); if(item) loadFolder(item.dataset.path); };
const dropZone=$("#drop-zone"); ["dragenter","dragover"].forEach(type=>dropZone.addEventListener(type,event=>{event.preventDefault();dropZone.classList.add("drag");})); ["dragleave","drop"].forEach(type=>dropZone.addEventListener(type,event=>{event.preventDefault();dropZone.classList.remove("drag");})); dropZone.addEventListener("drop",event=>{$("#torrent-file").files=event.dataTransfer.files;});

refresh(); setInterval(refresh, 1500);
