import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from patch_serveritem_iconless import patch_server_item_source


class PatchServerItemIconlessTests(unittest.TestCase):
    def test_removes_icon_and_state_lookups_but_keeps_server_name(self):
        source = '''
            override public function set data(param1:Object) : void
            {
                if(data)
                {
            if(data.icon)
            {
               _loc2_ = ApplicationDomain.currentDomain.getDefinition("" + data.icon) as Class;
               _loc3_ = new _loc2_();
               _icon_pic.removeAll();
               _icon_pic.addChild(_loc3_);
               _icon_pic.x = 20;
               _icon_pic.y = this.height - _icon_pic.height - 10;
            }
            if(data.name)
            {
               _name_txt.text = "" + data.name;
            }
            if(data.n == 0)
            {
               _loc2_ = ApplicationDomain.currentDomain.getDefinition("clip_server_0") as Class;
               _loc3_ = new _loc2_();
               _state_pic.removeAll();
               _state_pic.addChild(_loc3_);
               _state_pic.x = this.width - _state_pic.width - 20;
               _state_pic.y = this.height - _state_pic.height >> 1;
            }
            else
            {
               _loc2_ = ApplicationDomain.currentDomain.getDefinition("clip_server_1") as Class;
               _loc3_ = new _loc2_();
               _state_pic.removeAll();
               _state_pic.addChild(_loc3_);
               _state_pic.x = this.width - _state_pic.width - 20;
               _state_pic.y = this.height - _state_pic.height >> 1;
            }
            private function initBack() : void
            {
            }
        '''

        patched = patch_server_item_source(source)

        self.assertIn('_name_txt.text = "" + data.name;', patched)
        self.assertNotIn('getDefinition(', patched)
        self.assertNotIn('_icon_pic.addChild', patched)
        self.assertNotIn('_state_pic.addChild', patched)

    def test_rejects_unrecognized_server_item_source(self):
        with self.assertRaisesRegex(ValueError, "expected one ServerItem data setter"):
            patch_server_item_source("package { public class ServerItem {} }")


if __name__ == "__main__":
    unittest.main()
