"""Search stays identical to the existing UI, including Unicode and pinyin."""
import json,shutil,subprocess,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from segment_search import matches
class SearchParity(unittest.TestCase):
 def test_matches_existing_ui(self):
  node=shutil.which('node')
  if not node:self.skipTest('Node required for frontend parity')
  root=Path(__file__).resolve().parents[1]
  values=['重庆银行女儿','Ｈｅｌｌｏ café','Straße','女儿绿树','长安快乐',0,None,'a_b-c d','中文😀']
  queries=['cqyh','chongqing','yin','nv','hello','cafe','strasse','straße','lvs','chang','zhang','快乐','0','','abcd','😀','不存在']
  cases=[[q,v] for q in queries for v in values]
  script="global.window=global;require(process.argv[1]);require(process.argv[2]);let s='';process.stdin.on('data',v=>s+=v);process.stdin.on('end',()=>process.stdout.write(JSON.stringify(JSON.parse(s).map(([q,v])=>StudentAgeSearch.matches(q,v)))));"
  expected=json.loads(subprocess.check_output([node,'-e',script,str(root/'search-pinyin.js'),str(root/'search.js')],input=json.dumps(cases).encode()))
  self.assertEqual([matches(q,v) for q,v in cases],expected)
if __name__=='__main__':unittest.main()
