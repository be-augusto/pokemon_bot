import subprocess
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class ReloadHandler(FileSystemEventHandler):
    def __init__(self, script_path):
        self.script_path = script_path
        self.process = self.start_script()

    def start_script(self):
        return subprocess.Popen(['python3', self.script_path])

    def on_modified(self, event):
        if event.src_path.endswith(self.script_path):
            print(f"{event.src_path} has been modified. Reloading...")
            self.process.terminate()
            self.process.wait()
            self.process = self.start_script()

if __name__ == "__main__":
    script = "bot.py"
    event_handler = ReloadHandler(script)
    observer = Observer()
    observer.schedule(event_handler, path='.', recursive=False)
    observer.start()
    print(f"Watching for changes in {script}...")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        event_handler.process.terminate()
    observer.join()