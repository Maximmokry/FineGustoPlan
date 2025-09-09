# FineGusto Plánovač — README pro nástupce

> **Stav dokumentace a zbytku projektu**  
> Ucelená dokumentace zcela chybí — nestihl jsem ji dokončit před ukončením spolupráce. Toto README proto slouží jako praktický průvodce pro převzetí. Otevřené věci a nedodělky jsou vedené v **GitHub Issues** tohoto repozitáře.

---

## 0) Stažení projektu a instalace

### Stažení z GitHubu
**Varianta A — Git:**
```bash
git clone https://github.com/Maximmokry/FineGustoPlan
cd Finegusto
```
**Varianta B — ZIP:**
- Na GitHubu klikni **Code → Download ZIP**, rozbal archiv a otevři složku projektu.

### Virtuální prostředí (doporučeno)
**Windows (PowerShell):**
```powershell
py -3.10 -m venv .venv
.venv\Scripts\Activate.ps1
```
**macOS / Linux:**
```bash
python3.10 -m venv .venv
source .venv/bin/activate
```

### Instalace závislostí
Pokud je v repu `requirements.txt`:
```bash
pip install -r requirements.txt
```
Je možné, že něco bude chybět.

### Příprava dat
V kořenové složce a ve složce `data/` musí být:
```
<repo>/
  plan.xlsx
  data/
    recepty.xlsx
    plan_udiren_template.xlsx
```

### První spuštění
```bash
python3 run.py
```
---

## 1) Co projekt dělá (stručný přehled)

Aplikace slouží k **převodu výrobního plánu (ve formě objednávek) na itineráře pro jednotlivé kroky výroby** (zatím v podstatě jen nákup a uzení, do budoucna snad balení i marinování) a k **plánování uzení**:

1. **Vstupy** - aby tento projekt fungoval, potřebuje ve složce `data` excelový soubor s recepturami `recepty.xlsx`, vzor excelu pro export plánu `plan_udiren_template.xlsx` a v kořenové složce excel `plán.xlsx`, do kterého se plní objednávky.

2. **Itinerář surovin** - Z receptur a plánu se vypočítá kolik surovin je třeba na jednotlivý expediční den (je třeba aby bylo nakoupeno x dní předem.) Tento itinerář se zobrazí při stisku tlačítka ingredience. Položky je možno odškrtávat tlačítkem koupeno. Po stisku tlačítka zmizí jednotlivý řádek. Tato informace se uloží do excel souboru `ingredience.xlsx`. Pokud jsou pro nějaký polotvar koupeny všechny ingredience, v itineráři polotovarů se podtrhne.

3. **Itinerář konečných polotovarů (SK 300)** z receptur a plánu finálních výrobků (SK 400) na konkrétní expediční dny. Výstup je přehled polotovarů které čekají na zaplánování do výroby. tz, které se v další obrazovce naplánují (a uloží), tak se označí příznakem „vyrobeno“ (soubor `polotovary.xlsx`) a příště se již nezobrazují.

4. **Plánovač uzení (Po–So, 4 udírny × 7 slotů)** — grafické přeskládání vybraných polotovarů do slotů. V současné době je téměř dokončenný (ale ne otestovaný) předplánovač, který to rozrřadí podle pravidel v souborech `services/smoke_rules.py` a `services/smoke_engine.py`. **Uložit** vygeneruje týdenní Excel z šablony.

Datovým podkladem je směrový graf sestavený z excelů (načtení data_loader.py, sestavení graph_builder.py), jehož jádro tvoří typy Node/Demand/Graph v graph_model.py, přičemž graph_store.py ho drží jako jediný zdroj pravdy a promítá do projekcí Přehled/Detaily pro GUI/Excel; potřeby polotovarů (SK 300) se počítají v semis_projection.py z požadavků na výrobky (SK 400) a GUI v PySimpleGUIQt je nad tímto modelem jen tenká vrstva.

---

## 2) Složky a klíčové moduly

> Názvy a role vycházejí z repa a naší konverzace. Prefix `gui/` a `services/` odpovídá logickému členění (ve zdrojích může být fyzicky jinak).

### GUI
- **`gui/main_window.py`** — start okna, načtení dat/grafu, tlačítka do dalších oken, „Načíst znovu“.
- **`gui/results_window.py`** — Itinerář surovin, možnost "odklikávání", aby zmizely
- **`gui/results_semis_window.py`** — **Plán polotovarů**: tabulky (Přehled/Detaily), weekly agregace, přepínání detailů, označování „vyrobeno“, podtržení „ready“, tlačítko **Naplánovat**.
- **`gui/smoke_plan_window.py`** — **Plán uzení**: kompaktní grid (4 udírny × 7 pozic), drag/swap, vyplnění dávek/poznámek, akce **Uložit** → zápis týdenního plánu do šablony.

### Doména a služby
- **`services/graph_model.py`** — datové entity: `Node`, `Demand`, `Graph`.
- **`services/data_loader.py`** — načtení **receptur** a **plánu** z Excelů, normalizace sloupců.
- **`services/graph_builder.py`** — sestavení grafu z receptur, rozšíření jmen, expand plánu → `demands`, promítnutí historických stavů do uzlů.
- **`services/graph_store.py`** — runtime „single source of truth“ (drží Graph), poskytuje DataFrame projekcí, API pro GUI (nastavení koupeno/vyrobeno, reload).
- **`services/semis_projection.py`** — projekce polotovarů do DF **Přehled** a **Detaily** (vč. vazby na finály 400).
- **`services/semi_excel_service.py`** — zápis `polotovary.xlsx` (listy **Prehled**, **Detaily**, uživatelský **Polotovary**), merge se starými výstupy se zachováním `vyrobeno=True` (pokud změna množství ≤ ~50 %); **při větší změně se stav resetuje (tj. „předělá se“)**
- **`services/smoke_excel_service.py`** — zápis týdenního plánu uzení do **šablony Excel** (autodetekce rozložení, čištění starých buněk, zápis názvů/dávek).
- **`services/smoke_paths.py`** — cesty pro šablonu a výsledné soubory plánu uzení (pondělí týdne v názvu).
- **`services/smoke_sync_service.py`** — výpočet příznaků **naplánováno**/`smoking_date` pro položky dle `base_id` na základě `plan_df`.
- **`services/smoke_plan_service.py`** — kapacitní logika „v2“ bez GUI (split položek do slotů, generace `plan_df` a uložení).
- **`services/smoke_capacity.py`** — kapacitní parametry slotů (na udírnu, případně na typ).
- **`services/readiness.py`** — výpočet „ready“ (všechny listové ingredience v podstromu **koupené**).
- **`services/compute_common.py`, `services/data_utils.py`** — normalizace klíčů, převody datových typů (hlavně `datum`), tolerantní lookupy sloupců.
- **`services/paths.py`** — centrální řešení relativních cest (režim z repa vs. „frozen“ build).
- **`services/gui_helpers.py`** — pomůcky pro rekreaci oken (přepínání režimů bez ztráty pozice/scrollu).
- **`services/smoke_orchestrator.py`** — skriptová/automatizační cesta k vygenerování a uložení `plan_df` bez GUI.
- **A další** - pomocné soubory atd, snad by neměly být potřeba.

---

## 3) Datový model a datové toky

### 3.1 Doménové entity
- **Node**: `id=(SK, RC)`, `name`, `unit`, `edges` (děti), stavy `bought` (pro listy), `produced` (pro 300/400).
- **Demand**: požadavek na výrobu finálu: `key=(datum, 400, rc)`, `qty`.
- **Graph**: `nodes: Dict[NodeId, Node]`, `demands: List[Demand]`.

### 3.2 DataFrames (typicky)
- **Polotovary – Detaily**: `datum`, `polotovar_sk`, `polotovar_rc`, `polotovar_nazev`, `potreba`, `jednotka`, `vyrobeno` (bool), + odkaz na finál (400).  
- **Polotovary – Přehled**: shodné sloupce bez rozlišení finálu (agregace).  
- **Weekly režim**: agregace po týdnech (Po–Ne) + klíč **SK/RC/Název/MJ**.

### 3.3 Excel rozhraní („souvislé Excelly“)

**Vstupy**
- `data/recepty.xlsx` — Obsahuje receptury.
- `plan.xlsx` — provozní plán finálních výrobků (neboli prostě objednávky).

**Průběžné / výstupní**
- `ingredience.xlsx` — seznam nakupovaných surovin (výstup pro nákup).
- `polotovary.xlsx` — hlavní výstup pro 300:
  - **Sheet `Prehled`** — agregovaný přehled (jeden řádek na polotovar+datum).
  - **Sheet `Detaily`** — rozpad na „z čeho se vzal“ (vazba na 400).
  - **Sheet `Polotovary`** — „hezčí“ uživatelský list pro ruční práci.
  - **Sloupce** (minimálně): viz *3.2 DataFrames*.

**Plán uzení**
- Šablona: `data/plan_udiren_template.xlsx`.  
- Výstupy: `results/plan uzeni/plan_uzeni_YYYY_MM_DD.xlsx` — `YYYY_MM_DD` je **pondělí** daného týdne.  
- Zápis zahrnuje: názvy položek do slotů, **dávky** (pokud vyplněny), případně poznámky a hlavičky dnů (Po–So). Autodetekce rozložení šablony probíhá heuristicky (start bloků) 


---

## 4) Běh, CLI a build

### 4.1 Rychlé spuštění (dev)
```bash
python3 run.py
```
> Po startu se načtou data, sestaví graf a otevře se hlavní okno s přechody do **Polotovary** a **Plán uzení**.

### 4.2 Testy (pytest)
```bash
# Spuštění všech testů
pytest

# Tišší výstup
pytest -q

# Konkrétní test/soubor
pytest tests/test_uc5_semis.py::test_uc5_weekly_grouping_click_marks_all_in_week -q
```
Struktura testů odpovídá „UC scénářům“ (viz kapitola 5). Při pádech na datech typicky pomůže zkontrolovat typy `datum` a normalizaci klíčů.

### 4.3 Build/distribuce (exe)
```bash
# PyInstaller (příklad):
 pyinstaller --onefile --windowed run.py
```
Cesty k souborům se v běhu **přizpůsobují** tomu, zda jde o repozitář nebo „frozen“ build (viz `services/paths.py`).

---

## 5) Testy — co pokrývají (UC scénáře)
**doplnit** (je jich hodně, názvy docela odpovídají jejich účelu)

---

## 7) Instalace & závislosti

- **Python** 3.10+  
- **Knihovny**: `pandas`, `openpyxl`, `PySimpleGUIQt` (běží nad Qt), případně `PySide6` (dle prostředí).  
- Volitelně: `pyinstaller` pro build.  
- `requirements.txt`, použij: `pip install -r requirements.txt`.  (je možné, že není úplně aktuální)


---

## 8) Známé problémy

Na githubu v sekci issues
---
Gl
