"""The GUI script must at least parse as a browser script. `node --check` is not enough: it parses a file as a
CommonJS module, where a top-level `return` is legal, so it passed a broken app.js that blanked the whole GUI."""

import shutil
import subprocess
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "navis" / "web" / "app.js"


@unittest.skipUnless(shutil.which("node"), "needs node")
class WebAssets(unittest.TestCase):
    def test_app_js_parses_as_a_browser_script(self):
        r = subprocess.run(["node", "-e", "new (require('vm').Script)(require('fs').readFileSync(process.argv[1], 'utf8'))", str(APP)],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr[-600:])

    def test_the_parse_check_really_rejects_a_top_level_return(self):
        r = subprocess.run(["node", "-e", "new (require('vm').Script)('function f(){}\\nreturn 1;')"], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)  # the very mistake that shipped


if __name__ == "__main__":
    unittest.main()
