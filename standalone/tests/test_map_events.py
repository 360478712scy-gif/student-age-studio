import unittest
from unittest.mock import patch
from test_scoped_save import ScopedSaveTests
import server as b
from map_events import sync

class MapEventTests(unittest.TestCase):
 setUp=ScopedSaveTests.setUp
 write=ScopedSaveTests.write
 save=ScopedSaveTests.save
 def test_entry_exit_save_and_reopen(self):
  self.write('MapCfg',{'12':{'id':12,'name':'客运站','type':0}})
  self.write('EvtTypeCfg',{'777':{'id':777,'name':'保留','future':1}})
  for kind in (912,812):
   event={'id':1,'type':kind,'title':'客运站剧情','talkId':[1],'condition':[]}
   self.save({'events':{'1':event}})
   cfg=b.read_json(self.cfg/'EvtTypeCfg.json')
   self.assertEqual(cfg[str(kind)],{'id':kind,'name':'客运站','type':[1],'emptyIsTrue':1})
   self.assertEqual(cfg['777']['future'],1)
   self.assertEqual(b.read_json(self.cfg/'EvtCfg.json')['1']['type'],kind)
   self.save({'events':{'1':event}})
   self.assertEqual(b.read_json(self.cfg/'EvtTypeCfg.json'),cfg)
 def test_preserve_overrides_and_unreadable_tables(self):
  for unreadable in ({'EvtTypeCfg.json':True},{'MapCfg.json':True}):
   maps={};touched=set();sync({'1':{'type':912}},maps,touched,{'12':{'id':12,'type':0}}, {},unreadable);self.assertEqual(touched,set())
  maps={'EvtTypeCfg.json':{'912':{'id':912,'future':1}}};touched=set()
  sync({'1':{'type':912}},maps,touched,{'12':{'id':12,'type':0}}, {},{})
  self.assertEqual(maps['EvtTypeCfg.json']['912'],{'id':912,'future':1});self.assertEqual(touched,set())
