"""File watcher for catalog YAML changes - triggers auto-relock."""

import sys
import time
from pathlib import Path
from threading import Thread


def watch_catalog_files(catalog_dir: Path, callback, poll_interval: float = 1.0) -> Thread:
    """Watch catalog directory for file changes.
    
    Args:
        catalog_dir: Directory containing catalog YAML files
        callback: Function to call when files change
        poll_interval: How often to check (seconds)
    
    Returns:
        Thread object (daemonized)
    """
    def watcher():
        mtimes = {}
        
        # Initialize mtimes
        for yaml_file in catalog_dir.glob("*.yaml"):
            try:
                mtimes[str(yaml_file)] = yaml_file.stat().st_mtime
            except (OSError, FileNotFoundError):
                pass
        
        while True:
            try:
                time.sleep(poll_interval)
                
                for yaml_file in catalog_dir.glob("*.yaml"):
                    try:
                        current_mtime = yaml_file.stat().st_mtime
                        file_str = str(yaml_file)
                        
                        if file_str not in mtimes:
                            # New file
                            mtimes[file_str] = current_mtime
                            callback(file_str, "created")
                        elif mtimes[file_str] != current_mtime:
                            # File modified
                            mtimes[file_str] = current_mtime
                            callback(file_str, "modified")
                    except (OSError, FileNotFoundError):
                        pass
                
                # Check for deleted files
                deleted = [f for f in mtimes if not Path(f).exists()]
                for deleted_file in deleted:
                    del mtimes[deleted_file]
                    callback(deleted_file, "deleted")
                    
            except Exception:
                # Keep watching even if errors occur
                pass
    
    thread = Thread(target=watcher, daemon=True)
    thread.start()
    return thread
