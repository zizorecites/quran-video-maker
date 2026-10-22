"""
Quran Video Maker - by @zizorecites

Opens the app window. Also:
    python main.py --dev        run without a window, open the printed link in a browser
    python main.py --selftest   check everything the app needs works on this computer
"""

import os
import sys
import time
from pathlib import Path


def _quiet_console():
    """A built app has no Terminal to print to, so keep a log file instead."""
    from qvm import paths
    paths.make_dirs()
    if getattr(sys, "frozen", False) or sys.stdout is None:
        log = open(paths.HOME / "log.txt", "a", encoding="utf-8", buffering=1)
        log.write(f"\n--- opened {time.ctime()} ---\n")
        sys.stdout = sys.stderr = log


def selftest():
    """Run on GitHub for both Mac and Windows before anything is published."""
    import tempfile
    from qvm import core, paths
    print("python", sys.version)
    exe = core.setup_engine()
    print("ffmpeg:", exe)
    print("video codec:", core.q.VIDEO_CODEC[:2])
    assert exe, "no ffmpeg"
    import ctranslate2, faster_whisper, av, uharfbuzz, freetype  # noqa: F401
    print("listener parts load:", faster_whisper.__version__, ctranslate2.__version__)
    import arabic_text
    assert arabic_text.AVAILABLE, "Arabic drawing is not available"
    ar, en, counts = core.quran()
    assert counts[2] == 286
    work = Path(tempfile.mkdtemp())
    # a 4 second test sound
    audio = work / "test.wav"
    core.q.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                "sine=frequency=330:duration=4", str(audio)])
    total = core.q.audio_length(audio)
    print("test sound length:", total)
    words = core.q.mushaf_arabic(ar[(112, 1)])
    slide = work / "s.png"
    core.q.render_slide(words + " " + core.q.ayah_marker(1),
                        "Say, O Prophet, He is Allah, the One and Only.").save(slide)
    for size in ((1920, 1080), (1080, 1920)):
        out = work / f"out_{size[0]}.mp4"
        core.q.render_slide(words, "Say", size).save(slide)
        core.q.build(audio, [slide], [(0.0, total)], out, None,
                     progress=lambda f: None, size=size)
        got = core.q.audio_length(out)
        print("made", out.name, out.stat().st_size, "bytes,", got, "s")
        assert out.stat().st_size > 10000 and got > 3
    # one engine-only listen check: the model is not downloaded on GitHub
    print("listener ready here:", core.model_ready())
    print("SELFTEST OK")


def main():
    args = sys.argv[1:]
    here = Path(__file__).resolve().parent
    if not getattr(sys, "frozen", False):
        sys.path.insert(0, str(here))
    if "--selftest" in args:
        # a built app may have no console, so the result also goes to a file
        log_path = os.environ.get("QVM_SELFTEST_LOG")
        if log_path or sys.stdout is None:
            log = open(log_path or "selftest.txt", "w", encoding="utf-8", buffering=1)
            sys.stdout = sys.stderr = log
        try:
            selftest()
        except BaseException:
            import traceback
            traceback.print_exc()
            print("SELFTEST FAILED", flush=True)
            sys.exit(1)
        sys.exit(0)
    _quiet_console()
    from qvm import core, native, paths, server
    core.setup_engine()
    httpd, url = server.serve()
    if "--dev" in args or os.environ.get("QVM_DEV"):
        print("open", url, flush=True)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return
    import webview
    from webview.dom import DOMEventHandler

    window = webview.create_window(paths.APP_NAME, url, width=1280, height=820,
                                   min_size=(1000, 680), background_color="#0e1311")
    native.WINDOW = window

    def on_drop(e):
        files = (e.get("dataTransfer") or {}).get("files") or []
        got = [f.get("pywebviewFullPath") for f in files if f.get("pywebviewFullPath")]
        if got:
            core.add_paths(got)
            try:
                window.evaluate_js("window.app && app.refresh()")
            except Exception:
                pass

    def nothing(e):
        pass

    def bind(win):
        try:
            win.dom.document.events.dragenter += DOMEventHandler(nothing, True, True)
            win.dom.document.events.dragover += DOMEventHandler(nothing, True, True, debounce=500)
            win.dom.document.events.drop += DOMEventHandler(on_drop, True, True)
        except Exception as e:                       # older systems: buttons still work
            print("drag and drop not available:", e)

    webview.start(bind, window)
    core.stop()


if __name__ == "__main__":
    main()
