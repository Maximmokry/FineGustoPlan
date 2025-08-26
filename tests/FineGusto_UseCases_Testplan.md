# Use Cases (UC1--UC12)

Tento dokument shrnuje všechny definované Use Cases (UC) pro aplikaci
FineGusto a obsahuje také testovací plán (testplan tabulku).

------------------------------------------------------------------------

## Přehled Use Cases

### UC1 -- Výpočet potřeby ingrediencí

-   Spočítá ingredience z plánu a receptur.
-   Uloží do `vysledek.xlsx` se sloupcem `koupeno`.
-   GUI zobrazuje jen ne-koupené.

### UC2 -- Výpočet potřeby polotovarů (uzení)

-   Spočítá polotovary z plánu.
-   Zapíše do `polotovary.xlsx` se sloupcem `vyrobeno`.
-   GUI zobrazuje jen ne-vyrobené.

### UC3 -- Označení ingrediencí jako koupeno

-   Klik na **Koupeno** uloží stav do `vysledek.xlsx` a položka zmizí z
    výpisu.

### UC4 -- Označení polotovarů jako naplánováno

-   Klik na **Naplánováno** uloží stav do `polotovary.xlsx`.

### UC5 -- Agregace ingrediencí napříč dny

-   Přepínač „Sčítat napříč daty" agreguje položky se stejným SK/RC.

### UC6 -- Agregace polotovarů po týdnech

-   Přepínač „Součet na týden" seskupí položky Po--Ne.

### UC7 -- Zobrazení detailů polotovarů

-   Přepínač „Zobrazit podsestavy (detail)" ukáže rozpad na výrobky.

### UC8 -- Spolupráce s Excelem obousměrně

-   Uživatel může editovat Excel (přejmenovat sloupce, typy, prázdná
    pole...).
-   Aplikace odolně mapuje sloupce, normalizuje čísla a nikdy nespadne.
-   Sloupce `koupeno`/`vyrobeno` se vytvoří při zápisu, pokud chybí.
-   Při přepočtu se dělá merge se zachováním odškrtaných položek.

### UC9 -- Přebudování výstupů po změnách plánu/receptur

-   Změny v plánu se přenesou do výstupů.
-   Zvýšení množství → zvýší potřebu.
-   Snížení nebo zmizení položky → zmenší/odstraní řádek.
-   Zachování stavů `koupeno`/`vyrobeno`.

### UC10 -- Výpis a export pro provoz

-   `Polotovary` list slouží pro tisk/export s master + podřádky.
-   `vysledek.xlsx` sdílí stav nákupu.

### UC11 -- Chybové a hraniční situace (robustnost)

-   Chybějící/poškozené soubory → hláška, aplikace běží dál.
-   Zamčený Excel → hláška.
-   Podivné hodnoty (NaN, „150,0") → bezpečně normalizováno.
-   Vše hotovo → hláška místo prázdného okna.

### UC12 -- Zavření aplikace

-   „Konec" zavře všechna okna.
-   Uložený stav zůstane v Excelu.

------------------------------------------------------------------------

## Testplan tabulka

  -----------------------------------------------------------------------------------------------------------------------
  UC             Scénář         Setup / Vstupy        Kroky (headless)                             Očekávaný výsledek
  -------------- -------------- --------------------- -------------------------------------------- ----------------------
  UC1            Výpočet        `plan.xlsx` +         `compute_plan()` → `ensure_output_excel()` → `vysledek.xlsx` se
                 ingrediencí    receptury             `open_results()`                             sloupcem
                                                                                                   `koupeno=False`, okno
                                                                                                   jen ne-koupené

  UC2            Výpočet        `plan.xlsx`           `compute_plan_semifinished()` →              `polotovary.xlsx` se 3
                 polotovarů                           `ensure_output_semis_excel()` →              listy,
                                                      `open_semis_results()`                       `vyrobeno=False`, GUI
                                                                                                   jen ne-vyrobené

  UC3            Klik Koupeno   `vysledek.xlsx` se 3  `open_results()` → klik `-BUY-0-`            Řádek má
                                řádky                                                              `koupeno=True`, zmizí
                                                                                                   z GUI

  UC4            Klik           `polotovary.xlsx` se  `open_semis_results()` → klik `-SEMI-0-`     Řádek má
                 Naplánováno    2 řádky                                                            `vyrobeno=True`

  UC5            Agregace       2 dny, stejná položka `_build_table_layout(..., aggregate=True)`   Součet, jedno tlačítko
                 ingrediencí                                                                       group

  UC6            Weekly semis   2 řádky v jednom      `_aggregate_weekly()`                        Součet Po--Ne, label
                                týdnu                                                              „DD.MM.YYYY --
                                                                                                   DD.MM.YYYY"

  UC7            Detail semis   1 master + detaily    `_build_rows(..., show_details=True)`        Podřádky s `↳ Název`,
                                                                                                   master s poznámkou

  UC8            Excel          Ručně změněné         Načíst a zapsat                              Sloupce najdou,
                 tolerance      sloupce/typy                                                       `koupeno`/`vyrobeno`
                                                                                                   vytvořeny, čísla
                                                                                                   normalizována

  UC9            Recompute      Změna plánu 100→200   Re-run výpočtu                               `potreba=200`, stav
                 merge                                                                             True zachován

  UC10           Export         `Prehled`+`Detaily`   `ensure_output_semis_excel()`                `Polotovary` s
                                                                                                   hlavičkou, podřádky a
                                                                                                   poznámkami

  UC11           Robustnost     Chybějící list / NaN  Otevřít/uložit                               Hláska, žádný crash,
                                / zamčený soubor                                                   normalizace

  UC12           Zavření        Otevřená okna         Event `-EXIT-`                               Všechna okna zavřena,
                                                                                                   stav uložen
  -----------------------------------------------------------------------------------------------------------------------
