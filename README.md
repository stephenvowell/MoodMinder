# Mood Minder

Current version: 1.0.2.

A Windows desktop mood journal that helps you see personal patterns over ~30 days — mood (1–10), emotions, sleep, food, people, conversations, events, location, and thoughts.

Built with Python + Tkinter. Styled after [stephenv.net](https://stephenv.net).

## Features

- **Daily check-ins** with mood score and emotion tags  
- **Life context:** sleep, food, who you ate with, who you talked to, topics, events, location, thoughts  
- **Insights:** 7-day / 30-day averages and confidence  
- **Charts:** mood over time, sleep vs mood, emotions on low days, correlate probabilities  
- **Depression correlation log:** dated low-mood days (≤4) with factor probabilities  
- **Why this mood:** plain-language explanation from your own history  
- **Save PDF** (then optional print), export text, backup JSON  
- Hover **tooltips** + Help  

## Quick start

```bat
python app.py
```

Or after install: `run.bat`

## Install on another PC

See [`SETUP.txt`](SETUP.txt).

- **`install.bat`** — checks for Python, creates `.venv`, adds shortcuts  
- **`build_standalone.bat`** — builds `dist\MoodMinder.exe`  

## How to use

1. Log mood (1–10) and tag emotions  
2. Fill sleep, food, people, events, location, thoughts when you can  
3. After enough days, open **Insights** and **Charts**  
4. Use the **Depression correlation log** for low days and probabilities  
5. Select a day to read **Why this mood**  
6. **Save PDF** for a shareable report (asks before printing)  

## Disclaimer

Mood Minder is a **personal pattern journal**, not a medical device, diagnosis, or treatment.  
If you are in crisis, seek professional help.

## Project layout

| File | Purpose |
|------|---------|
| `app.py` | Tkinter UI |
| `mood_engine.py` | Pattern analyzer + explanations |
| `pdf_export.py` | PDF writer |
| `install.bat` / `install.ps1` | Windows installer |
| `run.bat` | Launch helper |
| `build_standalone.bat` | One-file EXE build |

Data files `mood_log.json` and `mood_settings.json` stay local (gitignored).

## Requirements

- Windows 10/11 recommended  
- Python 3.10+ with tkinter  
- No third-party packages required to run  

## License

MIT — see [`LICENSE`](LICENSE)
