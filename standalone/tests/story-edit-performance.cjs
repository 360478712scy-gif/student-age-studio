'use strict';
// Regression guards for the story-editing hot paths: the saved signature must not walk the
// 50k-entry ownership map, text edits must not rebuild the whole list, and link-neutral
// mutations must not enumerate or renumber the whole mod.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const I = require('../indexed-talks.js');
const source = fs.readFileSync(path.join(__dirname, '../app.js'), 'utf8');
const take = (start, end) => {
  const from = source.indexOf(start), to = source.indexOf(end, from);
  assert(from >= 0, 'missing source marker: ' + start);
  assert(to > from, 'missing end marker: ' + end);
  return source.slice(from, to);
};
const clone = v => I.clone(v);
const line = marker => {
  const from = source.indexOf(marker);
  assert(from >= 0, 'missing source marker: ' + marker);
  return source.slice(from, source.indexOf('\n', from));
};
const context = extra => {
  const box = { console, IndexedTalks: I, clone, ...extra };
  vm.createContext(box);
  return box;
};

// 1. The signature keeps the ownership map out of the serialized document and uses plain
// JSON for the 50k order array. Changing only owners must not change the signature.
{
  const box = context({ S: null });
  vm.runInContext(take('function signatureFromParts(', '// Undo keeps'), box);
  const S = {
    doc: { talks: { 1: { id: 1 } }, events: {}, options: {}, talkOwners: { 1: { marker: 'OWNERS_MARKER' } } },
    order: [1], deleted: [], replacements: {}, premises: {}, branchFolders: {},
    pinned: { talks: new Set(), options: new Set(), events: new Set() },
  };
  box.S = S;
  const signature = box.currentSignature();
  assert(!signature.includes('OWNERS_MARKER'), 'talkOwners leaked into the signature');
  const parts = I.parse(signature);
  assert.equal(parts.length, 7);
  assert.equal(parts[0].talkOwners, undefined);
  assert.deepEqual(parts[1], [1]);
  S.doc.talkOwners = { 1: { marker: 'CHANGED' } };
  assert.equal(box.currentSignature(), signature, 'owner-only change changed the signature');
}

// 2. Seeding the ownership snapshot must reuse the live map as the base; repeated snapshots
// with the same map must not enumerate it, while a changed map still produces a correct delta.
{
  const box = context({});
  vm.runInContext(take('const snapshotBases', '// entry.doc keeps'), box);
  const owners = { 1: [1], 2: [1] };
  box.seedOwnershipSnapshot(owners);
  assert.equal(box.ownershipSnapshotDelta(owners), box.ownershipSnapshotDelta(owners));
  const guarded = new Proxy(owners, { ownKeys() { throw Error('owners scanned'); } });
  box.seedOwnershipSnapshot(guarded);
  assert.doesNotThrow(() => box.ownershipSnapshotDelta(guarded));
  const seeded = { 1: [1], 2: [1] };
  box.seedOwnershipSnapshot(seeded);
  const delta = box.ownershipSnapshotDelta({ 1: [1], 2: [1, 2] });
  assert.deepEqual(box.objectRestore(delta), { 1: [1], 2: [1, 2] });
}

// 3. Option text edits update only the option and its rendered folder title. They must not
// rebuild the dialogue list, which was the 1.6s-per-key browser path.
{
  const title = { innerHTML: '' };
  const node = { dataset: { folder: '1:101' }, querySelector: () => title };
  let histories = 0, dirty = 0, lists = 0;
  const box = context({
    S: { branchFolders: { '1:101': { optionId: 101 } } },
    document: { querySelectorAll: () => [node] },
    StudentAgeRecordLabels: { html: (id, value) => `[${id}] ${value}` },
    history: () => histories++, updateTextDirty: () => dirty++, renderList: () => lists++,
  });
  vm.runInContext(take('function updateOptionTextCard', 'function setSpeakerName'), box);
  const option = { id: 101, content: '旧选项' };
  box.updateOptionContent(option, '新选项');
  assert.equal(option.content, '新选项');
  assert.equal(title.innerHTML, '[101] 新选项');
  assert.equal(histories, 1);
  assert.equal(dirty, 1);
  assert.equal(lists, 0, 'option typing must not rebuild the talk list');
}

// 4. The display-name field is a text edit, not a structural mutation: no ownership sync,
// no renumber scheduling, no full render.
{
  const row = { id: 1, roleName: '' };
  let mutates = 0, histories = 0, dirty = 0, cards = 0, previews = 0;
  const box = context({
    S: { doc: { talks: { 1: row } } }, editable: () => true, talk: () => row,
    history: () => histories++, updateTextDirty: () => dirty++,
    updateTalkTextCard: () => cards++, updatePreviewText: () => previews++,
    mutate: () => { mutates++; },
  });
  vm.runInContext(line('function setSpeakerName'), box);
  box.setSpeakerName(' 测试名字 ');
  assert.equal(row.roleName, '测试名字');
  assert.equal(mutates, 0, 'display name must not enter the structural mutation pipeline');
  assert.deepEqual([histories, dirty, cards, previews], [1, 1, 1, 1]);
}

// 5. A link-neutral mutation must not build a whole-table Set, recompute ownership, or
// schedule auto-renumbering. A link change still performs both.
{
  let version = 1, keysCalls = 0, syncs = 0, external = 0, renumbers = 0;
  const keys = ['1', '2'];
  const info = { get linkVersion() { return version; }, keys: () => { keysCalls++; return keys.slice(); } };
  const talks = new Proxy({}, { ownKeys() { throw Error('whole table enumerated'); } });
  const S = { doc: { talks, options: { 101: { id: 101 } }, events: { 1: { id: 1 } }, talkOwners: {} }, event: 1, selected: 1 };
  const box = context({
    S, Remote: { info: () => info }, editable: () => true, history: () => {},
    premiseHolders: () => new Set(), talk: () => null,
    syncOwnership: () => syncs++, syncExternal: () => external++,
    cleanLostPremises() {}, reconcileStoryClaims() {}, updateDirty: () => {},
    render: () => {}, scheduleRenumber: () => renumbers++,
    linkStamp: () => version,
  });
  vm.runInContext(take('function mutate(label', 'let textDirtyTimer'), box);
  box.mutate('text', () => {});
  assert.equal(renumbers, 0, 'text edit scheduled renumbering');
  assert.equal(syncs, 1);
  box.mutate('link', () => { version = 2; });
  assert.equal(renumbers, 1, 'link edit did not schedule renumbering');
  assert.equal(syncs, 2);
  box.mutate('add', () => { keys.push('3'); version = 3; });
  assert.equal(renumbers, 2);
  assert.equal(keysCalls >= 6, true, 'Remote key directory was not reused');
}

// 6. Option parent counts are reused while the talk link version is unchanged.
{
  let calls = 0, version = 1;
  const Branches = { optionParentCounts: () => { calls++; return new Map(); } };
  const Remote = { info: () => ({ linkVersion: version }) };
  const box = context({ Branches, Remote });
  vm.runInContext(take('let optionCountsCache=null', 'function renderList'), box);
  const doc = { talks: {} };
  box.optionParentCountsFor(doc);
  box.optionParentCountsFor(doc);
  assert.equal(calls, 1);
  version = 2;
  box.optionParentCountsFor(doc);
  assert.equal(calls, 2);
  box.optionParentCountsFor({ talks: {} });
  assert.equal(calls, 3);
}

// 7. The save payload handles the ownership map separately from the doc tables: an
// unchanged map is omitted, a changed map is sent, and it is not mistaken for a table.
{
  const owners = { 1: [1] };
  const S = {
    project: { id: 'p' }, revision: 'r',
    doc: { talks: { 1: { id: 1 } }, events: {}, options: {}, talkOwners: owners },
    savedOwners: owners, order: [1], deleted: [], replacements: {}, premises: {}, branchFolders: {},
    idMappings: {},
  };
  const savedDoc = { talks: { 1: { id: 1 } }, events: {}, options: {} };
  S.saved = JSON.stringify([savedDoc, [1], [], {}, {}, {}, { talks: [], options: [], events: [] }]);
  const box = context({
    S, Remote: { info: () => null }, IndexedTalks: I, clone,
    pinnedSnapshot: () => ({ talks: [], options: [], events: [] }),
  });
  vm.runInContext(take('function changedStoryPayloadFrom', 'async function save()'), box);
  assert.equal('talkOwners' in box.changedStoryPayloadFrom(), false);
  S.savedOwners = {};
  assert.deepEqual(box.changedStoryPayloadFrom().talkOwners, owners);
}

// 8. Dirty checking must not walk the 50k ownership map while the live and saved maps
// are the same object (the normal state after loading a project).
{
  const owners = new Proxy({ 1: [1] }, { ownKeys() { throw Error('owners scanned'); } });
  const box = context({ S: { doc: { talkOwners: owners }, savedOwners: owners } });
  vm.runInContext(line('function sameValue') + '\n' + line('function ownersDiffer'), box);
  assert.equal(box.ownersDiffer(), false);
}

// 9. Selecting a line that is already in the rendered list updates that card and the
// editor/preview only; rebuilding the 100-card list was the selection long task.
{
  const selectedCard = { classList: { add() {}, remove() {} }, setAttribute() {} };
  const folder = { dataset: { folder: '1:101' }, classList: { add() {}, remove() {} } };
  let lists = 0, editors = 0, previews = 0, selections = 0, scrolls = 0;
  const document = {
    querySelector: selector => selector.includes('.talk-card[data-id=') ? selectedCard : null,
    querySelectorAll: selector => selector.includes('.branch-folder') ? [folder] : [],
  };
  const box = context({
    S: { selected: 1, activeFolder: '1:101' }, document,
    renderChrome() {}, renderEditor: () => editors++, renderPreview: () => previews++,
    storySelection: { render: () => selections++ }, renderList: () => lists++,
    $: () => ({ scrollTop: 1, scrollTo: () => scrolls++ }),
  });
  vm.runInContext(line('function updateSelectedTalkView'), box);
  assert.equal(box.updateSelectedTalkView(), true);
  assert.deepEqual([lists, editors, previews, selections, scrolls], [0, 1, 1, 1, 1]);
}

console.log('story-edit-performance: signature, snapshot, option/name input, mutation gating, option-count cache, selection update and save payload passed');
