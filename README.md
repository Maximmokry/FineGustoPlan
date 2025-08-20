# Finegusto GUI

Tento projekt je desktopová aplikace postavená na Pythonu, PySimpleGUIQt a PySide6.
Aplikace využívá knihovny pandas a openpyxl pro práci s tabulkami a daty.

## Požadavky

- Python 3.11 (doporučeno)

- Git

- pip (součástí Pythonu)

## Instalace

1. Naklonuj repozitář:

```
git clone https://github.com/Maximmokry/FineGustoPlan
cd Finegusto
```

1. Vytvoř a aktivuj virtuální prostředí:
```
python -m venv venv
# Windows (PowerShell)
.\venv\Scripts\Activate.ps1
# Linux / Mac
source venv/bin/activate
```

3. Nainstaluj závislosti:
```
pip install -r requirements.txt
```
## Spuštění aplikace
```
python3 gui_qt.py
```

## Sestavení spustitelného souboru (Windows .exe)

Aplikaci lze převést na .exe pomocí PyInstalleru.

1. Nainstaluj PyInstaller:
```
pip install pyinstaller
```

1. Sestav aplikaci:
```
pyinstaller --onefile --windowed gui_qt.py
```

1. Hotový .exe soubor najdeš ve složce:
```
dist/gui_qt.exe
```
## Struktura projektu
```
Finegusto/
│── gui_qt.py          # hlavní aplikace  
│── requirements.txt   # seznam závislostí  
│── README.md          # tento soubor  
│── .gitignore         # ignorované soubory pro Git  
```
## Použité knihovny

- PySimpleGUIQt – GUI framework

- PySide6 – Qt binding

- pandas – práce s daty

- openpyxl – Excel soubory