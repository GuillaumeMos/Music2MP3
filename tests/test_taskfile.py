from pathlib import Path
import unittest


class TaskfileTests(unittest.TestCase):
    def test_default_run_uses_qt_entrypoint(self):
        text = Path("Taskfile.yml").read_text(encoding="utf-8")
        run_block = _task_block(text, "run")
        tk_block = _task_block(text, "run:tk")

        self.assertIn("qt_app.py", run_block)
        self.assertNotIn(" app.py", run_block)
        self.assertIn(" app.py", tk_block)


def _task_block(text: str, task_name: str) -> str:
    lines = text.splitlines()
    marker = f"  {task_name}:"
    for i, line in enumerate(lines):
        if line == marker:
            out = [line]
            for child in lines[i + 1:]:
                if child.startswith("  ") and not child.startswith("    "):
                    break
                out.append(child)
            return "\n".join(out)
    raise AssertionError(f"Task {task_name!r} not found")
