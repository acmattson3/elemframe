const $ = selector => document.querySelector(selector);
const sides = {
  removable: {path: '', items: [], selected: new Set(), request: 0},
  local: {path: '', items: [], selected: new Set(), request: 0}
};
const videoExtensions = new Set(['mp4','mov','webm','m4v','avi','mpg','mpeg','mpe','mts','m2ts','m2t','mod','tod','vob','dv','3gp','3g2','wmv','asf','mkv','ts','mxf','flv']);
const photoExtensions = new Set(['jpg','jpeg','png','gif','webp','bmp','avif','tif','tiff','heic','heif','hif','mpo','cr2','cr3','crw','nef','nrw','arw','sr2','srf','orf','rw2','raf','pef','dng','raw','rwl','3fr','iiq']);
function displayName(path, directory = false) {
  const name = path.split('/').pop();
  const extension = name.split('.').pop().toLowerCase();
  const dot = name.lastIndexOf('.');
  return !directory && dot > 0 ? name.slice(0, dot) : name;
}
function itemName(side, path) {
  const item = sides[side].items.find(item => item.path === path);
  return item?.label ?? displayName(path, item?.directory);
}
const pathJoin = (parent, name) => parent ? `${parent}/${name}` : name;
let drives = [], polling = false, managerOpen = false, copying = false;
let dashboardTimer = null, dashboardDeadline = 0, slideshowRequest = 0;
function status(message) { $('#status').textContent = message; }
function screen(id) {
  stopDashboardCountdown();
  slideshowRequest++;
  managerOpen = id === 'manager';
  document.querySelectorAll('.screen').forEach(el => el.classList.toggle('active', el.id === id));
  if (id === 'dashboard') startDashboardCountdown();
}
function stopDashboardCountdown() {
  clearInterval(dashboardTimer);
  dashboardTimer = null;
}
function startDashboardCountdown() {
  stopDashboardCountdown();
  dashboardDeadline = Date.now() + 30000;
  function update() {
    if (!$('#dashboard').classList.contains('active')) { stopDashboardCountdown(); return; }
    const seconds = Math.max(0, Math.ceil((dashboardDeadline - Date.now()) / 1000));
    $('#dashboardCountdown').textContent = `Slideshow starts in ${seconds}s`;
    if (seconds === 0 && !$('#play').disabled) { stopDashboardCountdown(); startSlideshow(); }
  }
  dashboardTimer = setInterval(update, 250);
  update();
}
async function api(endpoint, body) {
  const response = await fetch('/api/' + endpoint, body === undefined ? {} : {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
  });
  const result = await response.json();
  if (!response.ok) {
    const error = new Error(result.detail || `Request failed (${response.status})`);
    error.status = response.status;
    throw error;
  }
  return result;
}
function applyListing(side, items, preserveSelection = false) {
  const state = sides[side];
  const selected = preserveSelection ? new Set([...state.selected].filter(path => items.some(item => item.path === path))) : new Set();
  if (JSON.stringify(items) !== JSON.stringify(state.items) || !preserveSelection) {
    state.items = items;
    state.selected = selected;
    render(side);
  }
}
async function refresh(side, preserveSelection = false) {
  const state = sides[side], path = state.path, request = ++state.request;
  try {
    const result = await api(`list?side=${side}&path=${encodeURIComponent(path)}`);
    if (request !== state.request || path !== state.path) return;
    applyListing(side, result.items, preserveSelection);
  } catch (error) {
    if (request !== state.request || path !== state.path) return;
    if (path && [403, 404].includes(error.status)) {
      state.path = '';
      await refresh(side);
      status(side === 'removable' ? 'Drive or folder unavailable. Returned to drives.' : 'Folder unavailable. Returned to library.');
    } else status(error.message);
  }
}
async function pollRemovable() {
  if (!managerOpen || polling) return;
  polling = true;
  try {
    const result = await api('list?side=removable');
    drives = result.items;
    const state = sides.removable;
    if (state.path && !drives.some(drive => state.path === drive.path || state.path.startsWith(drive.path + '/'))) {
      state.path = '';
      state.request++;
      state.selected.clear();
      state.items = drives;
      render('removable');
      status('Drive disconnected. Returned to drives.');
    } else if (!state.path) applyListing('removable', drives, true);
    else await refresh('removable', true);
  } catch (error) { status(error.message); }
  finally { polling = false; }
}
function icon(kind) {
  const paths = {
    folder: '<path d="M3 7h7l2 2h9v11H3z"/><path d="M3 7V4h7l2 3"/>',
    video: '<rect x="3" y="5" width="13" height="14" rx="2"/><path d="m16 10 5-3v10l-5-3"/>',
    photo: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8" cy="8" r="1.5"/><path d="m3 17 6-6 4 4 3-3 5 5"/>',
    file: '<path d="M5 3h9l5 5v13H5zM14 3v6h5"/>'
  };
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round" aria-hidden="true">${paths[kind]}</svg>`;
}
function renderSelection(side) {
  const state = sides[side], count = state.selected.size;
  $(`#${side}Count`).textContent = `${count} selected`;
  $(`[data-deselect="${side}"]`).classList.toggle('hidden', count === 0);
  $(`[data-deleteall="${side}"]`).classList.toggle('hidden', count < 2);
  for (const action of ['rename', 'delete']) $(`[data-action="${action}"][data-side="${side}"]`).disabled = count !== 1;
  $(`[data-action="mkdir"][data-side="${side}"]`).disabled = side === 'removable' && !state.path;
  document.querySelectorAll(`[data-list="${side}"] .item`).forEach(node => {
    const selected = state.selected.has(node.dataset.path);
    node.classList.toggle('selected', selected);
    node.setAttribute('aria-pressed', String(selected));
  });
}
function parentPath(side) {
  const path = sides[side].path;
  if (side === 'removable') {
    const drive = drives.find(item => path === item.path || path.startsWith(item.path + '/'));
    if (!drive || path === drive.path) return '';
  }
  return path.split('/').slice(0, -1).join('/');
}
function render(side) {
  const state = sides[side], list = $(`[data-list="${side}"]`);
  list.replaceChildren();
  const back = document.createElement('button');
  back.className = 'back-row';
  back.type = 'button';
  back.textContent = '↑ Go back';
  back.disabled = !state.path;
  back.onclick = () => navigate(side, parentPath(side));
  list.append(back);
  if (!state.items.length) {
    const empty = document.createElement('div');
    empty.className = 'empty';
    empty.textContent = side === 'removable' && !state.path ? 'Insert a USB drive or SD card.' : 'No files or folders here.';
    list.append(empty);
  }
  for (const item of state.items) {
    const node = document.createElement('button');
    node.className = 'item' + (item.directory ? ' directory' : '');
    node.dataset.path = item.path;
    const extension = item.name.split('.').pop().toLowerCase();
    const kind = item.directory ? 'folder' : videoExtensions.has(extension) ? 'video' : photoExtensions.has(extension) ? 'photo' : 'file';
    const glyph = document.createElement('span');
    glyph.className = `glyph ${kind}`;
    glyph.innerHTML = icon(kind);
    const name = document.createElement('span');
    name.className = 'name';
    name.textContent = item.label ?? displayName(item.name, item.directory);
    node.append(glyph, name);
    if (item.directory) {
      const open = document.createElement('span');
      open.className = 'open';
      open.textContent = 'Open ›';
      node.append(open);
    }
    node.onclick = event => {
      if (node.dataset.dragged === 'true') { delete node.dataset.dragged; return; }
      if (item.drive || event.target.closest('.open')) { navigate(side, item.path); return; }
      if (state.selected.has(item.path)) state.selected.delete(item.path);
      else state.selected.add(item.path);
      renderSelection(side);
    };
    node.ondblclick = () => { if (item.directory) navigate(side, item.path); };
    node.draggable = false;
    node.onpointerdown = event => { if (!item.drive) startPointerDrag(event, side, item.path, node); };
    list.append(node);
  }
  renderSelection(side);
  const crumb = $(`[data-crumb="${side}"]`);
  crumb.replaceChildren();
  function addCrumb(label, path) {
    if (crumb.childNodes.length) { const slash = document.createElement('span'); slash.textContent = '/'; crumb.append(slash); }
    const button = document.createElement('button');
    button.textContent = label;
    button.onclick = () => navigate(side, path);
    crumb.append(button);
  }
  addCrumb(side === 'local' ? 'Library' : 'Drives', '');
  let base = '', remainder = state.path;
  if (side === 'removable' && state.path) {
    const drive = drives.find(item => state.path === item.path || state.path.startsWith(item.path + '/'));
    if (drive) { addCrumb(drive.name, drive.path); base = drive.path; remainder = state.path.slice(base.length).replace(/^\//, ''); }
  }
  for (const part of remainder.split('/').filter(Boolean)) { base = pathJoin(base, part); addCrumb(part, base); }
}
async function navigate(side, path) { sides[side].path = path; await refresh(side); }

// Every modal resolves on selection or Escape, with explicit copy conflict actions.
let closeDialog = null;
function choose(title, choices, value) {
  return new Promise(resolve => {
    if (closeDialog) closeDialog(null);
    const backdrop = $('#dialogBackdrop'), input = $('#dialogInput'), buttons = $('.dialogButtons');
    const previousFocus = document.activeElement;
    $('#dialogTitle').textContent = title;
    input.classList.toggle('hidden', value === undefined);
    input.value = value ?? '';
    buttons.replaceChildren();
    const done = result => {
      backdrop.classList.add('hidden');
      closeDialog = null;
      previousFocus?.focus();
      resolve(result);
    };
    closeDialog = done;
    choices.forEach(({label, result, primary}) => {
      const button = document.createElement('button');
      button.textContent = label;
      if (primary) button.className = 'primary';
      button.onclick = () => done(result === 'input' ? input.value : result);
      buttons.append(button);
    });
    input.onkeydown = event => {
      if (event.key === 'Enter') { event.preventDefault(); done(input.value); }
    };
    backdrop.classList.remove('hidden');
    (value === undefined ? buttons.firstChild : input).focus();
  });
}
function dialog(title, value = '', needsInput = true) {
  return choose(title, [{label:'Cancel', result:null}, {label:needsInput ? 'OK' : 'Delete', result:needsInput ? 'input' : true, primary:true}], needsInput ? value : undefined);
}
async function deleteSelected(side) {
  const paths = [...sides[side].selected];
  if (!paths.length) return;
  if (!await dialog(`Permanently delete ${paths.length === 1 ? itemName(side, paths[0]) : paths.length + ' selected items'}?`, '', false)) return;
  let deleted = 0;
  const errors = [];
  for (const path of paths) {
    try { await api('delete', {side, path}); deleted++; }
    catch (error) { errors.push(error.message); }
  }
  await refresh(side);
  status(`Deleted ${deleted} item(s).${errors.length ? ' ' + errors.join('; ') : ''}`);
}
async function doCopy(from, to, targetPath = sides[to].path, moving = false, selectedPaths = null) {
  if (copying) return;
  const paths = selectedPaths ? [...selectedPaths] : [...sides[from].selected];
  const endpoint = moving ? 'move' : 'copy', past = moving ? 'Moved' : 'Copied';
  if (!paths.length) { status('Select files or folders first.'); return; }
  if (to === 'removable' && !targetPath) { status('Open a drive before copying to it.'); return; }
  copying = true;
  $('#copyRight').disabled = $('#copyLeft').disabled = true;
  let copied = 0, skipped = 0;
  const errors = [];
  try {
    for (const path of paths) {
      const request = {source_side:from, source_paths:[path], target_side:to, target_path:targetPath};
      status(`${moving ? 'Moving' : 'Copying'} ${itemName(from, path)}…`);
      try { const result = await api(endpoint, request); copied++; errors.push(...(result.issues || []).map(name => `${name} cannot be displayed`)); }
      catch (error) {
        if (error.status !== 409) { errors.push(error.message); continue; }
        const conflict = await choose(`${itemName(from, path)} already exists.`, [
          {label:'Skip', result:null}, {label:'Replace', result:'replace'}, {label:'Rename', result:'rename', primary:true}
        ]);
        if (!conflict) { skipped++; continue; }
        try { const result = await api(endpoint, {...request, conflict}); copied++; errors.push(...(result.issues || []).map(name => `${name} cannot be displayed`)); }
        catch (failure) { errors.push(failure.message); }
      }
    }
  } finally {
    await refresh(to);
    if (moving && from !== to) await refresh(from);
    status(`${past} ${copied} item(s), skipped ${skipped}.${errors.length ? ' Errors: ' + errors.join('; ') : ''}`);
    copying = false;
    $('#copyRight').disabled = $('#copyLeft').disabled = false;
  }
}
for (const side of ['removable', 'local']) {
  const list = $(`[data-list="${side}"]`);
  list.ondragover = event => event.preventDefault();
  list.ondrop = event => {
    event.preventDefault();
    const from = event.dataTransfer.getData('text/plain'), folder = event.target.closest('.item.directory');
    if (!sides[from]) return;
    if (folder) doCopy(from, side, folder.dataset.path, true);
    else if (from !== side) doCopy(from, side);
  };
  $(`[data-side="${side}"].refresh`).onclick = () => refresh(side);
  $(`[data-deselect="${side}"]`).onclick = () => { sides[side].selected.clear(); renderSelection(side); };
  $(`[data-deleteall="${side}"]`).onclick = () => deleteSelected(side);
}
for (const button of document.querySelectorAll('[data-action]')) button.onclick = async () => {
  const {side, action} = button.dataset, state = sides[side], selected = [...state.selected];
  try {
    if (action === 'delete') { await deleteSelected(side); return; }
    if (action === 'mkdir') {
      const name = await dialog('New folder name');
      if (!name) return;
      await api('mkdir', {side, path:state.path, name});
    } else if (action === 'rename' && selected.length === 1) {
      const item = state.items.find(item => item.path === selected[0]);
      const name = await dialog('Rename to', item?.label ?? displayName(selected[0], item?.directory));
      if (!name) return;
      await api('rename', {side, path:selected[0], name, stem_only:!item?.directory});
    }
    await refresh(side);
    status('Done.');
  } catch (error) { status(error.message); }
};
function startPointerDrag(event, side, path, node) {
  if (event.button !== 0 || event.target.closest('.open')) return;
  const {clientX:x, clientY:y} = event;
  const dragPaths = new Set(sides[side].selected);
  dragPaths.add(path);
  const dragLabel = dragPaths.size === 1 ? itemName(side, path) : `${dragPaths.size} items`;
  let active = false;
  function cleanup() {
    window.removeEventListener('pointermove', move);
    window.removeEventListener('pointerup', end);
    window.removeEventListener('pointercancel', cleanup);
    $('#dragGhost').classList.add('hidden');
    document.querySelectorAll('.drop-target').forEach(el => el.classList.remove('drop-target'));
    setTimeout(() => delete node.dataset.dragged, 200);
  }
  function move(ev) {
    if (!active && Math.hypot(ev.clientX-x, ev.clientY-y) > 16) {
      active = true;
      node.setPointerCapture(ev.pointerId);
      node.dataset.dragged = 'true';
      sides[side].selected = new Set(dragPaths);
      renderSelection(side);
      $('#dragGhost').classList.remove('hidden');
      $('#dragGhost').textContent = 'Copy ' + dragLabel;
    }
    if (active) {
      $('#dragGhost').style.left = (ev.clientX+8)+'px'; $('#dragGhost').style.top = (ev.clientY+8)+'px';
      document.querySelectorAll('.drop-target').forEach(el => el.classList.remove('drop-target'));
      const folder = document.elementFromPoint(ev.clientX, ev.clientY)?.closest('.item.directory');
      if (folder && !(folder.closest('.pane').id === `${side}Pane` && dragPaths.has(folder.dataset.path))) folder.classList.add('drop-target');
      $('#dragGhost').textContent = (folder ? 'Move ' : 'Copy ') + dragLabel;
    }
  }
  function end(ev) {
    cleanup();
    if (!active) return;
    ev.preventDefault();
    const target = document.elementFromPoint(ev.clientX, ev.clientY);
    const pane = target?.closest('.pane'), folder = target?.closest('.item.directory');
    const to = pane?.id === 'localPane' ? 'local' : pane?.id === 'removablePane' ? 'removable' : null;
    if (to && folder) {
      if (to !== side || !dragPaths.has(folder.dataset.path)) doCopy(side, to, folder.dataset.path, true, dragPaths);
    } else if (to && to !== side) doCopy(side, to, sides[to].path, false, dragPaths);
  }
  window.addEventListener('pointermove', move);
  window.addEventListener('pointerup', end, {once:true});
  window.addEventListener('pointercancel', cleanup, {once:true});
}
$('#copyRight').onclick = () => doCopy('removable', 'local');
$('#copyLeft').onclick = () => doCopy('local', 'removable');
$('#manage').onclick = async () => { screen('manager'); await pollRemovable(); await Promise.all([refresh('local'), refresh('removable')]); };
$('#home').onclick = () => screen('dashboard');
setInterval(pollRemovable, 1500);

// Two independently loaded media layers remain present throughout a crossfade.
let slideFiles = [], slideIndex = 0, slideToken = 0, slideTimer = null;
let currentMedia = null, shuffleOn = false, advancing = false;
let shuffleQueue = [], recentSlides = [];
let volume = 0, volumeHideTimer = null, volumeDragging = false;
function refillShuffleQueue() {
  // One entry per library item: a full round must finish before refilling.
  shuffleQueue = [...slideFiles];
  for (let i = shuffleQueue.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [shuffleQueue[i], shuffleQueue[j]] = [shuffleQueue[j], shuffleQueue[i]];
  }
}
function nextFile() {
  if (!slideFiles.length) return null;
  if (!shuffleOn) return slideFiles[slideIndex++ % slideFiles.length];
  if (!shuffleQueue.length) refillShuffleQueue();
  // Keep repeats at least ten selections apart when the library permits it.
  // With fewer items, spread repeats across the entire available library.
  const historyLength = Math.min(9, slideFiles.length - 1);
  const recent = new Set(historyLength ? recentSlides.slice(-historyLength) : []);
  let index = shuffleQueue.findIndex(file => !recent.has(file.path));
  if (index === -1) {
    // The library may have changed since the previous slideshow session.
    // Prefer the remaining item that was seen longest ago.
    index = shuffleQueue.reduce((oldest, file, i) =>
      recentSlides.lastIndexOf(file.path) < recentSlides.lastIndexOf(shuffleQueue[oldest].path) ? i : oldest, 0);
  }
  const [file] = shuffleQueue.splice(index, 1);
  recentSlides.push(file.path);
  recentSlides = recentSlides.slice(-9);
  return file;
}
function disposeMedia(media) {
  if (!media) return;
  media.onload = media.onerror = media.onended = media.onloadeddata = null;
  if (media.tagName === 'VIDEO') { media.pause(); media.removeAttribute('src'); media.load(); }
  media.remove();
}
function stopSlideshow() {
  slideToken++;
  clearTimeout(slideTimer);
  advancing = false;
  [...$('#slideStage').children].forEach(disposeMedia);
  currentMedia = null;
  $('#slideResume').classList.add('hidden');
  screen('dashboard');
}
function readyMedia(media, url) {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => done(new Error('Media took too long to load')), 15000);
    function done(error) {
      clearTimeout(timeout);
      media.onload = media.onloadeddata = media.onerror = null;
      if (error) reject(error); else resolve();
    }
    media.onerror = () => done(new Error('Cannot play this media'));
    if (media.tagName === 'VIDEO') media.onloadeddata = () => done();
    else media.onload = () => done();
    media.src = url;
    if (media.tagName === 'VIDEO') media.load();
  });
}
async function playVideo(media, token) {
  try { await media.play(); $('#slideResume').classList.add('hidden'); }
  catch (error) {
    if (token !== slideToken || currentMedia !== media) return;
    if (error.name === 'NotAllowedError') $('#slideResume').classList.remove('hidden');
    else slideTimer = setTimeout(() => nextSlide(token), 1000);
  }
}
async function nextSlide(token) {
  if (token !== slideToken || advancing || !slideFiles.length) return;
  advancing = true;
  clearTimeout(slideTimer);
  const file = nextFile(), media = document.createElement(file.video ? 'video' : 'img');
  media.className = 'slide-media';
  media.style.opacity = '0';
  if (file.video) { media.playsInline = true; media.preload = 'auto'; media.volume = volume; media.muted = volume === 0; }
  else media.alt = file.name;
  $('#slideStage').append(media);
  try {
    try {
      const prepared = await api('prepare', {path:file.path});
      if (token !== slideToken) { disposeMedia(media); return; }
      await readyMedia(media, prepared.url);
    }
    catch (error) {
      if (token !== slideToken) { disposeMedia(media); return; }
      const prepared = await api('prepare', {path:file.path, fallback:true});
      if (token !== slideToken) { disposeMedia(media); return; }
      await readyMedia(media, prepared.url);
    }
    if (token !== slideToken) { disposeMedia(media); return; }
    const outgoing = currentMedia;
    const transition = outgoing ? Number($('#transitionTime').value)*1000 : 0;
    media.style.transition = `opacity ${transition}ms linear`;
    if (outgoing) outgoing.style.transition = media.style.transition;
    // Keep the outgoing frame opaque underneath: the incoming layer replaces it
    // progressively, without a dip through black.
    media.getBoundingClientRect();
    media.style.opacity = '1';
    await new Promise(resolve => setTimeout(resolve, transition));
    if (token !== slideToken) { disposeMedia(media); return; }
    disposeMedia(outgoing);
    currentMedia = media;
    $('#slideFilename').textContent = file.name;
    $('#slideEmpty').style.display = 'none';
    advancing = false;
    if (file.video) {
      media.onended = () => nextSlide(token);
      media.onerror = () => { slideTimer = setTimeout(() => nextSlide(token), 1000); };
      await playVideo(media, token);
    } else slideTimer = setTimeout(() => nextSlide(token), Number($('#displayTime').value)*1000);
  } catch (error) {
    disposeMedia(media);
    if (token !== slideToken) return;
    advancing = false;
    $('#slideFilename').textContent = `Could not display ${file.name}; skipping…`;
    slideTimer = setTimeout(() => nextSlide(token), 1500);
  }
}
async function startSlideshow() {
  if (!$('#dashboard').classList.contains('active')) return;
  stopDashboardCountdown();
  const request = ++slideshowRequest;
  try {
    const files = await api('slideshow');
    if (request !== slideshowRequest || !$('#dashboard').classList.contains('active')) return;
    slideFiles = files;
    shuffleOn = $('#shuffle').checked;
    shuffleQueue = [];
    const availablePaths = new Set(slideFiles.map(file => file.path));
    recentSlides = recentSlides.filter(path => availablePaths.has(path));
    slideIndex = 0;
    advancing = false;
    const token = ++slideToken;
    $('#slideEmpty').style.display = slideFiles.length ? 'none' : 'block';
    $('#slideFilename').textContent = '';
    screen('slideshow');
    nextSlide(token);
  } catch (error) {
    if (request !== slideshowRequest) return;
    await choose(error.message, [{label:'OK', result:null}]);
    if ($('#dashboard').classList.contains('active')) startDashboardCountdown();
  }
}
$('#play').onclick = startSlideshow;
$('#slideResume').onclick = event => { event.stopPropagation(); if (currentMedia) playVideo(currentMedia, slideToken); };
function setVolume(value) {
  volume = Math.max(0, Math.min(1, Number(value)));
  $('#volumeSlider').value = volume;
  $('#volumeSlider').setAttribute('aria-valuetext', `${Math.round(volume*100)} percent`);
  $('#slideStage').querySelectorAll('video').forEach(video => { video.volume = volume; video.muted = volume === 0; });
  $('#volumeButton').textContent = volume === 0 ? '🔇' : volume < 0.5 ? '🔉' : '🔊';
  $('#volumeButton').setAttribute('aria-label', `Volume: ${Math.round(volume*100)} percent. Show volume slider`);
}
function collapseVolume() {
  $('#volumeSliderWrap').classList.add('collapsed');
  $('#volumeButton').setAttribute('aria-expanded', 'false');
}
function revealVolume() {
  $('#volumeSliderWrap').classList.remove('collapsed');
  $('#volumeButton').setAttribute('aria-expanded', 'true');
  clearTimeout(volumeHideTimer);
  if (!volumeDragging) volumeHideTimer = setTimeout(collapseVolume, 5000);
}
$('#volumeButton').onclick = () => {
  if ($('#volumeSliderWrap').classList.contains('collapsed')) revealVolume();
  else { clearTimeout(volumeHideTimer); collapseVolume(); }
};
$('#volumeSlider').oninput = event => { setVolume(event.target.value); queueSettings({volume}); revealVolume(); };
$('#volumeSlider').onpointerdown = () => { volumeDragging = true; revealVolume(); };
window.addEventListener('pointerup', () => { if (volumeDragging) { volumeDragging = false; revealVolume(); } });
window.addEventListener('pointercancel', () => { if (volumeDragging) { volumeDragging = false; revealVolume(); } });
$('#volumeSlider').onkeydown = revealVolume;
$('#volumeSlider').onfocus = revealVolume;
$('#slideshow').onclick = event => { if (!event.target.closest('#volumeControl') && !event.target.closest('#slideResume')) stopSlideshow(); };
for (const [id, output] of [['displayTime', 'displayValue'], ['transitionTime', 'transitionValue']]) {
  $('#'+id).oninput = event => { $('#'+output).textContent = event.target.value + 's'; queueSettings({[id === 'displayTime' ? 'display_time' : 'transition_time']: Number(event.target.value)}); };
}
window.addEventListener('keydown', event => {
  if (event.key === 'Escape') {
    if (closeDialog) closeDialog(null);
    else if ($('#slideshow').classList.contains('active')) stopSlideshow();
  }
});
setVolume(0);

// Save partial settings in order; the server atomically replaces config.json.
let pendingSettings = {}, savingSettings = false, settingsTimer = null;
function queueSettings(update) {
  Object.assign(pendingSettings, update);
  $('#settingsStatus').textContent = 'Saving settings…';
  clearTimeout(settingsTimer);
  settingsTimer = setTimeout(saveSettings, 150);
}
async function saveSettings() {
  if (savingSettings) return;
  savingSettings = true;
  try {
    while (Object.keys(pendingSettings).length) {
      const update = pendingSettings;
      pendingSettings = {};
      try { await api('config', update); }
      catch (error) { pendingSettings = {...update, ...pendingSettings}; throw error; }
    }
    $('#settingsStatus').textContent = '';
  } catch (error) { $('#settingsStatus').textContent = 'Settings could not be saved: ' + error.message; }
  finally { savingSettings = false; }
}
$('#shuffle').onchange = event => queueSettings({shuffle: event.target.checked});
window.addEventListener('pagehide', () => {
  if (Object.keys(pendingSettings).length) fetch('/api/config', {
    method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(pendingSettings), keepalive:true
  }).catch(() => {});
});
async function loadSettings() {
  const controls = ['displayTime', 'transitionTime', 'shuffle', 'volumeSlider', 'play'];
  controls.forEach(id => $('#'+id).disabled = true);
  try {
    const config = await api('config');
    $('#displayTime').value = config.display_time;
    $('#displayValue').textContent = config.display_time + 's';
    $('#transitionTime').value = config.transition_time;
    $('#transitionValue').textContent = config.transition_time + 's';
    $('#shuffle').checked = config.shuffle;
    setVolume(config.volume);
  } catch (error) { $('#settingsStatus').textContent = 'Settings could not be loaded: ' + error.message; }
  finally { controls.forEach(id => $('#'+id).disabled = false); }
}
loadSettings().finally(() => {
  if ($('#dashboard').classList.contains('active')) startDashboardCountdown();
});
