import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import support  # noqa: F401
from hue_backend import settings


class Migration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.legacy = root / "hue-wallpaper.json"
        env = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(root / "cfg")})
        env.start()
        self.addCleanup(env.stop)
        leg = mock.patch.object(settings, "LEGACY_WALLPAPER", self.legacy)
        leg.start()
        self.addCleanup(leg.stop)

    def test_legacy_config_is_persisted_on_first_load_and_kept(self):
        self.legacy.write_text(json.dumps({"enabled": True, "targets": ["a"]}))
        self.assertEqual(settings.load(), {"wallpaper": {"enabled": True, "targets": ["a"]}})
        self.assertEqual(json.loads(settings.path().read_text()), {"wallpaper": {"enabled": True, "targets": ["a"]}})
        self.assertEqual(stat.S_IMODE(settings.path().stat().st_mode), 0o600)
        self.assertFalse(settings.path().with_name("settings.json.tmp").exists())
        self.assertTrue(self.legacy.exists())

    def test_existing_settings_win_and_legacy_is_ignored(self):
        settings.save({"wallpaper": {"enabled": False}})
        self.legacy.write_text(json.dumps({"enabled": True}))
        self.assertEqual(settings.load(), {"wallpaper": {"enabled": False}})

    def test_nothing_to_migrate_writes_nothing(self):
        self.assertEqual(settings.load(), {})
        self.assertFalse(settings.path().exists())

    def test_unwritable_target_still_returns_the_migrated_config(self):
        self.legacy.write_text(json.dumps({"enabled": True}))
        with mock.patch.object(settings, "save", side_effect=OSError):
            self.assertEqual(settings.load(), {"wallpaper": {"enabled": True}})


if __name__ == "__main__":
    unittest.main()
