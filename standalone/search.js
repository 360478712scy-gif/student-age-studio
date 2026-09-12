/* Shared offline Chinese, English, pinyin and initial-letter matching. */
(()=>{
'use strict';
const cache=new Map(),dictionary=window.STUDIO_PINYIN||{};
const normalize=value=>String(value??'').normalize('NFKC').toLocaleLowerCase().replace(/ü/g,'v').normalize('NFD').replace(/[\u0300-\u036f]/g,'');
const compact=value=>value.replace(/[\s_\-'’]+/g,'');
function prepare(text){if(cache.has(text))return cache.get(text);const tokens=[...text].map(c=>dictionary[c]||[c]),value={tokens,full:tokens.map(v=>v[0]).join(''),initials:tokens.map(v=>v[0][0]||'').join('')};cache.set(text,value);if(cache.size>2048)cache.delete(cache.keys().next().value);return value;}
function alternatives(query,tokens,initials){let active=new Set();for(const variants of tokens){const next=new Set();active.add(0);for(const offset of active)for(const pronunciation of variants){const part=initials?pronunciation[0]:pronunciation;if(!part)continue;const tail=query.slice(offset);if(part.startsWith(tail))return true;if(tail.startsWith(part))next.add(offset+part.length);}active=next;}return false;}
function matches(query,...values){query=normalize(query).trim();if(!query)return true;const texts=values.flat().filter(v=>v!=null).map(normalize);if(texts.some(text=>text.includes(query)))return true;const roman=compact(query);if(!/^[a-z0-9]+$/.test(roman))return false;return texts.some(text=>{const value=prepare(compact(text));return value.full.includes(roman)||value.initials.includes(roman)||alternatives(roman,value.tokens,false)||alternatives(roman,value.tokens,true);});}
window.StudentAgeSearch={matches};
})();
