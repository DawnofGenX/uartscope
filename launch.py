"""UARTScope Pro Launcher - starts backend + desktop app"""
import subprocess
import sys
import os
import time

def get_base_path():
    """Get the base path (handles PyInstaller _MEIPASS for bundled .exe)"""
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))

def main():
    base_path = get_base_path()
    backend_path = os.path.join(base_path, "backend")
    
    # Start backend server in background
    print("[UARTScope] Starting backend server on :8080...")
    backend_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=backend_path if os.path.exists(backend_path) else base_path
    )
    
    # Wait for backend to be ready
    print("[UARTScope] Waiting for backend...")
    time.sleep(4)
    
    # Start NiceGUI desktop app
    print("[UARTScope] Starting desktop app on :3000...")
    print("[UARTScope] Open http://localhost:3000 in your browser")
    print("[UARTScope] Press Ctrl+C to quit")
    
    frontend_script = os.path.join(base_path, "desktop_app.py")
    frontend_proc = subprocess.Popen(
        [sys.executable, frontend_script],
        stdout=sys.stdout,
        stderr=sys.stderr,
        cwd=base_path
    )
    
    # Wait for either to exit
    try:
        while True:
            if backend_proc.poll() is not None:
                print("[Backend] Exited, shutting down...")
                frontend_proc.terminate()
                break
            if frontend_proc.poll() is not None:
                print("[Frontend] Exited, shutting down...")
                backend_proc.terminate()
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[UARTScope] Shutting down...")
    finally:
        backend_proc.terminate()
        try:
            backend_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            backend_proc.kill()
        frontend_proc.terminate()
        try:
            frontend_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            frontend_proc.kill()
    print("[UARTScope] Goodbye!")

if __name__ == "__main__":
    main()
