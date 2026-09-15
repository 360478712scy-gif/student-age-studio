const assert=require('node:assert/strict'),Text=require('../../standalone/dialogue-text.js');
const persons={0:{id:0,name:'白雨'},3:{id:3,name:'梁超杰'},4:{id:4,name:'A B'},5:{id:5,name:'同名'},6:{id:6,name:'同名'}};
const rows=[{speaker:'白雨',content:'你好 世界。\n这是下一行。\\n保留斜杠'}, {speaker:'A B',content:'  空格保留  '},{speaker:'旁白',content:''}];
const text=Text.serialize(rows),parsed=Text.parse('\uFEFF'+text.replace(/\n/g,'\r\n'),persons);assert.equal(parsed.errors.length,0);assert.equal(parsed.unmatched.length,0);assert.deepEqual(parsed.rows.map(({speaker,content})=>({speaker,content})),rows);assert.deepEqual(parsed.rows[0].roleIds,[0]);assert.deepEqual(parsed.rows[1].roleIds,[4]);assert.deepEqual(parsed.rows[2].roleIds,[]);assert.equal(text.split('\n').length,4);assert.equal(Text.parse('梁超杰 你好\n缺少分隔符\n\n未知 你好\n同名 你好',persons).errors.length,0);assert.deepEqual(Text.parse('未知 你好\n同名 你好',persons).unmatched,['未知','同名']);assert.deepEqual(Text.parse('未知 你好\n同名 你好',persons,{'未知':'narrator','同名':'5'}).rows.map(r=>r.roleIds),[[],[5]]);assert.equal(Text.parse('未知 你好',persons,{'未知':'9999'}).errors.length,1);assert.equal(Text.parse('旁白 测试\n'.repeat(2001),persons).errors.length,1);console.log('Dialogue TXT: escaping, newline, spaces, ID 0, name binding, malformed lines and import limits passed.');

const mixed=Text.parse('\uFEFF窗外下起了雨。\r\n白雨 今天还去吗？\r\n\r\n  两个人走出教室。\r\n梁超杰：当然。\r\n旁白 天渐渐暗了。\r\n白雨停下了脚步。',persons);
assert.deepEqual(mixed.errors,[]);assert.deepEqual(mixed.unmatched,[]);
assert.deepEqual(mixed.rows.map(r=>[r.speaker,r.content,r.roleIds,r.line]),[
 ['旁白','窗外下起了雨。',[],1],['白雨','今天还去吗？',[0],2],['旁白','两个人走出教室。',[],4],
 ['梁超杰','当然。',[3],5],['旁白','天渐渐暗了。',[],6],['旁白','白雨停下了脚步。',[],7]
]);
assert.equal(Text.parse('第一句。\\n第二句。',persons).rows[0].content,'第一句。\n第二句。');
assert.deepEqual(Text.parse(Text.serialize(mixed.rows),persons).rows.map(r=>[r.speaker,r.content,r.roleIds]),mixed.rows.map(r=>[r.speaker,r.content,r.roleIds]));
assert.equal(Text.parse('没有人名。\n'.repeat(2001),persons).errors.length,1);
assert.deepEqual(Text.parse('\n  \r\n',persons).rows,[]);
console.log('Plain narration: mixed speakers, CRLF/BOM, blank lines, known-name prefix, escaping, round trip and limit passed.');
const structured='旁白 开始\n选项 今天去吃烤肉\n白雨 烤肉\n选项：今天去吃萨莉亚\n梁超杰 披萨\n选项:空选项\n。\n旁白 正文\n分支2\n旁白 支线\n。\n分支\n旁白 另一支线\n。\n旁白 结束';
const tree=Text.parse(structured,persons);assert.deepEqual(tree.errors,[]);assert.equal(tree.rows.length,7);assert.deepEqual(tree.rows.sections.map(x=>[x.kind,x.parent,x.title,x.number]),[['option',0,'今天去吃烤肉',null],['option',0,'今天去吃萨莉亚',null],['option',0,'空选项',null],['condition',3,'',2],['condition',3,'',null]]);for(const sep of [' ',':','：']){const p=Text.parse(Text.serialize(tree.rows,sep),persons);assert.deepEqual(p.errors,[]);assert.deepEqual(p.rows.sections,tree.rows.sections);assert.deepEqual(p.rows.map(r=>[r.content,r.section]),tree.rows.map(r=>[r.content,r.section]));}
assert(Text.parse('旁白 a\n分支0\n旁白 b\n。',persons).errors.length);assert(Text.parse('。',persons).errors.length);assert.deepEqual(Text.parse('旁白 。\n旁白 选项:文本\n旁白 分支1',persons).rows.map(r=>r.content),['。','选项:文本','分支1']);
const nested=Text.parse('旁白 a\n选项 a\n旁白 b\n\t选项 b\n旁白 c\n\t。\n旁白 d\n。\n旁白 e',persons);assert.deepEqual(nested.errors,[]);assert.deepEqual(nested.rows.sections.map(s=>s.parent),[0,1]);assert.deepEqual(nested.rows.map(r=>r.section),[undefined,0,1,0,undefined]);
console.log('Structured TXT: sibling options, empty folder, colon forms, numbered/automatic branches, nested folders and round trip passed.');
