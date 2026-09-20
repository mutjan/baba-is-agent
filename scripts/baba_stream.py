"""Stream child output while retaining it for delta evaluation."""
import os
import selectors
import subprocess
import time


def stream_command(command, *, cwd, timeout, emit=print):
    proc = subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, start_new_session=True)
    chunks = []
    deadline = time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, timeout, output=b''.join(chunks))
                for key, _ in selector.select(min(remaining, .1)):
                    data = os.read(key.fileobj.fileno(), 65536)
                    if not data:
                        selector.unregister(key.fileobj)
                    else:
                        chunks.append(data)
                        emit(data.decode('utf-8', errors='replace'), end='', flush=True)
        return subprocess.CompletedProcess(command, proc.wait(timeout=max(.01, deadline-time.monotonic())),
                                           b''.join(chunks).decode('utf-8', errors='replace'), '')
    finally:
        if proc.poll() is None:
            # Stop the worker, but never replay a possibly dispatched key.
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        proc.stdout.close()
