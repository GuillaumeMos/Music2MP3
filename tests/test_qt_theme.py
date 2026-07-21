import unittest

import qt_app


class QtThemeTests(unittest.TestCase):
    def test_theme_uses_restrained_music_palette(self):
        qss = qt_app.APP_QSS.lower()
        for expected in ("#090909", "#121212", "#181818", "#1ed760", "#b3b3b3"):
            self.assertIn(expected, qss)
        for legacy in ("#ff006e", "#00f5ff", "#7b00ff", "#06070d", "#03040a"):
            self.assertNotIn(legacy, qss)

    def test_hero_has_no_decorative_paint_override(self):
        self.assertNotIn("paintEvent", qt_app.HeroWidget.__dict__)


if __name__ == "__main__":
    unittest.main()
