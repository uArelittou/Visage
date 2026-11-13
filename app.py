"""千面录桌面入口：在 127.0.0.1 的空闲端口起后端，再用 pywebview 开独立窗口。

    python app.py               # 正常启动（弹出窗口）
    python app.py --headless    # 只起后端，不开窗口，Ctrl+C 退出（调试/无桌面环境）
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
import threading
import time
from pathlib import Path

import uvicorn

from backend.api import create_app

HOST = "127.0.0.1"
ROOT = Path(__file__).resolve().parent
FRONTEND_DIST = ROOT / "frontend" / "dist"
WINDOW_TITLE = "千面录"


def start_backend(port: int = 0, timeout: float = 15.0) -> tuple[uvicorn.Server, threading.Thread, int]:
    """起后端线程，返回 (server, 线程, 实际端口)。port=0 由系统挑空闲端口。

    先自己绑定 socket 再交给 uvicorn，端口在绑定那一刻就被占住，不会出现「查到空闲、启动前被别人占走」。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((HOST, port))
    actual = sock.getsockname()[1]
    config = uvicorn.Config(
        create_app(frontend_dist=FRONTEND_DIST), host=HOST, port=actual,
        log_level="warning", access_log=False,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, name="uvicorn", daemon=True)
    thread.start()
    deadline = time.monotonic() + timeout
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            sock.close()
            raise RuntimeError("后端启动失败")
        time.sleep(0.05)
    return server, thread, actual


def stop_backend(server: uvicorn.Server, thread: threading.Thread) -> None:
    server.should_exit = True
    thread.join(timeout=10)


CARD_FILE_TYPES = ("角色卡 (*.png;*.webp;*.json)", "所有文件 (*.*)")


class NativeApi:
    """通过 pywebview 的 js_api 暴露给前端：Windows 原生的选择文件夹/文件对话框，返回绝对路径。
    窗口句柄放在带下划线的属性里：pywebview 会递归检查 js_api 的公开属性，公开窗口对象会卡死。"""

    def __init__(self) -> None:
        self._window = None

    def bind(self, window) -> None:
        self._window = window

    def pick_folder(self) -> str | None:
        import webview

        picked = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        return picked[0] if picked else None

    def pick_files(self) -> list[str]:
        import webview

        picked = self._window.create_file_dialog(
            webview.FileDialog.OPEN, allow_multiple=True, file_types=CARD_FILE_TYPES
        )
        return list(picked) if picked else []


def bind_drop(window) -> None:
    """拖进窗口的文件只有在 Python 端注册了 drop 监听后才带完整路径（pywebviewFullPath），
    浏览器里的 File 对象拿不到。路径取到后交给前端，走和对话框相同的「添加来源」流程。"""
    from webview.dom import DOMEventHandler

    def on_drop(event) -> None:
        files = event["dataTransfer"].get("files", [])
        paths = [f["pywebviewFullPath"] for f in files if f.get("pywebviewFullPath")]
        window.evaluate_js(f"window.__qmlDropped && window.__qmlDropped({json.dumps(paths)}, {len(files)})")

    window.dom.document.events.drop += DOMEventHandler(on_drop, False, False)


def _ensure_std_streams() -> None:
    # 打包成无控制台 exe 时 sys.stdout/stderr 为 None，uvicorn 配日志会调用 isatty() 直接崩溃。
    import os

    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    _ensure_std_streams()
    ap = argparse.ArgumentParser(description="千面录")
    ap.add_argument("--headless", action="store_true", help="只起后端，不开窗口")
    ap.add_argument("--port", type=int, default=0, help="指定端口，默认自动选空闲端口")
    args = ap.parse_args(argv)

    server, thread, port = start_backend(args.port)
    url = f"http://{HOST}:{port}/"
    try:
        if args.headless:
            print(f"千面录后端已启动: {url}", flush=True)
            while thread.is_alive():
                time.sleep(0.5)
        else:
            import webview  # 延迟导入：headless 与测试不需要窗口后端

            native = NativeApi()
            window = webview.create_window(
                WINDOW_TITLE, url, width=1360, height=860, min_size=(960, 600), js_api=native
            )
            native.bind(window)
            webview.start(bind_drop, window)  # 阻塞到窗口关闭
    except KeyboardInterrupt:
        pass
    finally:
        stop_backend(server, thread)
    return 0


if __name__ == "__main__":
    sys.exit(main())
