"""Start the app:  python run.py   then open http://127.0.0.1:8000"""
import socket

import uvicorn

from backend import settings


def lan_ip() -> str | None:
    """This computer's address on the local network (no traffic is actually sent)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return None


if __name__ == "__main__":
    print(f"\n  SapaRate на этом компьютере:  http://127.0.0.1:{settings.PORT}")
    if settings.HOST == "0.0.0.0":
        ip = lan_ip()
        if ip:
            print(f"  Для команды (та же Wi-Fi): http://{ip}:{settings.PORT}")
        print("  Если Windows спросит про доступ к сети — разрешите для частных сетей.\n")
    uvicorn.run("backend.main:app", host=settings.HOST, port=settings.PORT, reload=False)
