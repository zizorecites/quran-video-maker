# Quran Video Maker

**by [@zizorecites](https://www.tiktok.com/@zizorecites)**

Turn a Quran recitation into a video with the mushaf text and the English — a new
screen every time you take a breath, showing exactly what you said (repeats too).

**Download:** see the download page linked at the top of this project, or the
[Releases](../../releases/latest) page.

- Mac: Apple chip (M1 or newer), macOS 14 or newer
- Windows: 10 or 11, 64-bit

## What's in here

| | |
|---|---|
| `main.py` | starts the app |
| `qvm/` | the app: the list of recordings, making videos, settings, the screen editor |
| `ui/` | the app's screens |
| `engine/` | the video maker itself (listening, breaths, mushaf text, English matching) |
| `resources/` | Quran text, translation, word meanings, fonts |
| `build/` | how the Mac app and Windows installer are packed |
| `docs/` | the download page |
| `build/workflows/` | how GitHub builds the Mac and Windows versions and the download page (copied into `.github/workflows` when publishing) |
| `publish.command` | double-click on a Mac to send changes and build a new version |

## Run it from the source

    pip install -r requirements.txt
    python main.py            # opens the app
    python main.py --selftest # checks everything works

## Credits

- English: *The Clear Quran* by Dr. Mustafa Khattab
- Mushaf text and font: King Fahd Glorious Quran Printing Complex (Uthmanic Hafs)
- Word meanings: quran.com word-by-word
- Listening: Whisper (OpenAI), run by faster-whisper
