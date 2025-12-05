# live_subprocess.py
import subprocess, threading, logging

def run_command_stream(cmd, cwd=None, env=None, logger=None, level=logging.INFO, text=True):
    """
    Lance un sous-process et stream stdout/stderr vers le logger en temps réel.
    Retourne le code de sortie.
    """
    logger = logger or logging.getLogger(__name__)
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=text,
        bufsize=1,  # line-buffered
        universal_newlines=text
    )

    def _pump(pipe, log):
        try:
            for line in iter(pipe.readline, ''):
                line = line.rstrip("\n")
                if line:
                    log.log(level, line)
        except Exception:
            log.exception("live_subprocess: failed while reading process output")
        finally:
            try:
                pipe.close()
            except Exception:
                pass

    t = threading.Thread(target=_pump, args=(proc.stdout, logger), daemon=True)
    t.start()
    return_code = proc.wait()
    t.join(timeout=1)
    return return_code
