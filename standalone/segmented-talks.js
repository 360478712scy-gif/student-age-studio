/* Explicit asynchronous draft store for the experimental disk-page protocol.
 * Deliberately NOT a synchronous object/Proxy: an unloaded row is never missing.
 * The production editors must migrate their callers before using this store. */
(function(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.StudentAgeSegmentedTalks = api;
})(typeof window === 'object' ? window : globalThis, () => {
  'use strict';
  const bytes = value => new TextEncoder().encode(value).byteLength;
  const copy = value => JSON.parse(JSON.stringify(value));
  const snapshots = new WeakMap();

  function validateRow(id, text) {
    const row = JSON.parse(text);
    if (!row || Array.isArray(row) || typeof row !== 'object' || row.id !== Number(id))
      throw Error('对话区段与编号不一致。');
    return row;
  }

  function editableNumbers(text) {
    // Preserve unrepresentable future fields by refusing an unsafe JS rewrite.
    // Tokenize strings and numbers, so digits inside dialogue text do not count.
    const tokens = text.match(/"(?:[^"\\]|\\.)*"|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g) || [];
    for (const token of tokens) {
      if (token[0] === '"') continue;
      const value = Number(token), digits = token.split(/[eE]/)[0].replace(/[^0-9]/g, '').replace(/^0+/, '');
      if (!Number.isFinite(value) || (Number.isInteger(value) && !Number.isSafeInteger(value)) || digits.length > 15)
        throw Error('这句含有超出编辑精度的数值，已保留原记录，不能通过分段编辑改写。');
    }
  }

  class Draft {
    constructor(descriptor, request, {maxBytes = 2 * 1024 * 1024} = {}) {
      const info = descriptor?.segmentedTalks;
      if (info?.version !== 1 || typeof info.generation !== 'string' || !Array.isArray(info.ids)
          || new Set(info.ids).size !== info.ids.length || info.ids.some(id => !/^(0|[1-9][0-9]*)$/.test(id)))
        throw Error('分段目录格式无效。');
      if (!Number.isSafeInteger(maxBytes) || maxBytes <= 0) throw Error('缓存上限无效。');
      this.projectId = descriptor.project.id;
      this.generation = info.generation;
      this.revision = descriptor.revision;
      this.baseIds = new Set(info.ids);
      this.request = request;
      this.maxBytes = maxBytes;
      this.cache = new Map();
      this.cacheBytes = 0;
      this.originals = new Map();
      this.changes = new Map();
      this.saved = new Map();
      this.errors = new Map();
      this.loading = new Set();
      this.undoStack = [];
      this.redoStack = [];
      this.selection = 0;
      this.alive = true;
      this.group = null;
    }

    toJSON() { throw Error('分段草稿不是完整对话表，请使用显式增量保存或完整导出。'); }

    status(id) {
      id = String(id);
      if (this.changes.has(id)) return this.changes.get(id) === null ? 'deleted' : 'loaded';
      if (!this.baseIds.has(id)) return 'missing';
      if (this.originals.has(id) || this.cache.has(id)) return 'loaded';
      if (this.loading.has(id)) return 'loading';
      return this.errors.has(id) ? 'failed' : 'unloaded';
    }

    remember(id, text) {
      if (this.cache.has(id)) this.cacheBytes -= bytes(this.cache.get(id));
      this.cache.delete(id);
      const size = bytes(text);
      // A giant row may be used by its caller, but is not retained by the cache.
      if (size > this.maxBytes) return;
      this.cache.set(id, text);
      this.cacheBytes += size;
      while (this.cacheBytes > this.maxBytes) {
        const first = this.cache.keys().next().value;
        this.cacheBytes -= bytes(this.cache.get(first));
        this.cache.delete(first);
      }
    }

    async baseRows(ids) {
      if (!this.alive) throw Error('分段会话已关闭。');
      const found = new Map(), pending = [];
      for (const id of new Set(ids.map(String))) {
        if (!this.baseIds.has(id)) continue;
        if (this.originals.has(id)) found.set(id, this.originals.get(id));
        else if (this.cache.has(id)) {
          const text = this.cache.get(id);
          found.set(id, text);
          this.remember(id, text);
        } else pending.push(id);
      }
      for (let start = 0; start < pending.length; start += 100) {
        let remaining = pending.slice(start, start + 100);
        while (remaining.length) {
          const requested = remaining;
          requested.forEach(id => this.loading.add(id));
          try {
            const data = await this.request('/api/talk-segments/page', {
              projectId: this.projectId, generation: this.generation, ids: requested
            });
            if (!this.alive) throw Error('分段会话已关闭。');
            if (data.generation !== this.generation || data.revision !== this.revision
                || !Array.isArray(data.rows) || !Array.isArray(data.remaining) || !data.rows.length)
              throw Error('收到过期或不完整的对话区段，已有草稿保留。');
            const returned = new Set();
            for (const pair of data.rows) {
              if (!Array.isArray(pair) || pair.length !== 2 || typeof pair[1] !== 'string'
                  || !requested.includes(pair[0]) || returned.has(pair[0])) throw Error('返回的对话区段无效。');
              validateRow(pair[0], pair[1]);
              returned.add(pair[0]);
            }
            const rest = requested.filter(id => !returned.has(id));
            if (JSON.stringify(rest) !== JSON.stringify(data.remaining)) throw Error('对话分页缺少记录。');
            // Publish only after the entire response has passed validation.
            for (const [id, text] of data.rows) {
              found.set(id, text);
              this.remember(id, text);
              this.errors.delete(id);
            }
            remaining = rest;
          } catch (error) {
            requested.forEach(id => this.errors.set(id, error));
            throw error;
          } finally {
            requested.forEach(id => this.loading.delete(id));
          }
        }
      }
      return found;
    }

    async read(ids) {
      ids = [...new Set(ids.map(String))];
      const base = await this.baseRows(ids.filter(id => !this.changes.has(id)));
      const result = {};
      // Recheck changes after await: typing while a request was pending wins.
      for (const id of ids) {
        const text = this.changes.has(id) ? this.changes.get(id) : base.get(id);
        if (text != null) result[id] = validateRow(id, text);
      }
      return result;
    }

    async select(ids) {
      const sequence = ++this.selection;
      try {
        const rows = await this.read(ids);
        return sequence === this.selection && this.alive ? {accepted: true, rows} : {accepted: false};
      } catch (error) {
        if (sequence !== this.selection || !this.alive) return {accepted: false};
        throw error;
      }
    }

    snapshot() {
      const token = Object.freeze({});
      snapshots.set(token, {draft: this, changes: new Map(this.changes)});
      return token;
    }

    state(snapshot) {
      const value = snapshots.get(snapshot);
      if (value?.draft !== this) throw Error('草稿快照属于其他会话。');
      return value.changes;
    }

    history(group) {
      if (group == null || group !== this.group) {
        this.undoStack.push(this.snapshot());
        if (this.undoStack.length > 60) this.undoStack.shift();
      }
      this.redoStack = [];
      this.group = group;
    }

    async edit(id, change, group = null) {
      id = String(id);
      // Acquire the original before any mutation; cache eviction cannot lose it.
      const base = (await this.baseRows([id])).get(id);
      const text = this.changes.has(id) ? this.changes.get(id) : base;
      if (text == null) throw Error('对话不存在或已删除。');
      editableNumbers(text);
      const row = validateRow(id, text);
      const returned = change(row);
      if (returned?.then) throw Error('对话修改必须同步完成。');
      const next = JSON.stringify(row);
      validateRow(id, next);
      if (next === JSON.stringify(JSON.parse(text))) return;
      this.history(group);
      if (base != null) this.originals.set(id, base);
      if (base != null && next === JSON.stringify(JSON.parse(base))) this.changes.delete(id);
      else this.changes.set(id, next);
    }

    add(row) {
      const id = String(row?.id), text = JSON.stringify(row);
      validateRow(id, text);
      if (!/^(0|[1-9][0-9]*)$/.test(id) || this.baseIds.has(id) || this.changes.has(id)) throw Error('对话编号已占用或无效。');
      editableNumbers(text);
      this.history(null);
      this.changes.set(id, text);
    }

    async remove(ids) {
      ids = [...new Set(ids.map(String))];
      const base = await this.baseRows(ids);
      this.history(null);
      for (const id of ids) {
        if (base.has(id)) { this.originals.set(id, base.get(id)); this.changes.set(id, null); }
        else this.changes.delete(id);
      }
    }

    restore(snapshot) { this.changes = new Map(this.state(snapshot)); this.group = null; }
    undo() {
      if (!this.undoStack.length) return false;
      this.redoStack.push(this.snapshot()); this.restore(this.undoStack.pop()); return true;
    }
    redo() {
      if (!this.redoStack.length) return false;
      this.undoStack.push(this.snapshot()); this.restore(this.redoStack.pop()); return true;
    }

    patch(snapshot = this.snapshot()) {
      const current = this.state(snapshot), upsert = {}, deleted = [];
      for (const id of new Set([...current.keys(), ...this.saved.keys()])) {
        const now = current.has(id) ? current.get(id) : this.originals.get(id);
        const old = this.saved.has(id) ? this.saved.get(id) : this.originals.get(id);
        if (now === old || (now == null && old == null)) continue;
        if (now == null) deleted.push(Number(id)); else upsert[id] = validateRow(id, now);
      }
      return {version: 1, upsert, deleted};
    }

    acknowledge(snapshot) {
      // Only acknowledges this submitted snapshot, never input made after it.
      // The controller must rebase/reopen against the new server revision before
      // requesting any new pages. This method does not bypass source conflicts.
      this.saved = new Map(this.state(snapshot));
      this.group = null;
    }

    dirty() { const patch = this.patch(); return !!(Object.keys(patch.upsert).length || patch.deleted.length); }
    evict() { this.cache.clear(); this.cacheBytes = 0; }
    close() { this.alive = false; this.selection++; this.evict(); }
    stats() { return {cachedBytes: this.cacheBytes, cachedRows: this.cache.size, draftRows: this.changes.size, originalRows: this.originals.size}; }
  }

  return {Draft};
});
