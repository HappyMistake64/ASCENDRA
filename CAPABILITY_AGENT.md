# Agent s pamětí zkušeností a návrhy schopností

Agent vybírá nástroje podle cíle, jejich skutečných schémat a výsledků předchozích kroků. Zkušenosti ukládá pro další plánování. Může navrhnout opakovaně použitelný postup, který nezávislý evaluátor ověří a zpřístupní jako další nástroj.

## Ambice a dlouhodobý směr

Režimy `grow` a `demo` nyní standardně používají trvalý plán ambicí. Model navrhne směr rozvoje a tři milníky: **teď**, **další krok**, **náročnější výzva**. Každý obsahuje důvod, konkrétní další krok, cílový počet ověřených výsledků a kontrakt, podle kterého lze pokrok měřit. Plán je svázaný s uživatelskou misí a zůstává v paměti mezi spuštěními.

Další volba cíle i jednotlivých nástrojů dostává aktuální milník. Po neúspěšném nezávislém ověření dostane plánovač pokyn zmenšit rozsah a nejprve diagnostikovat příčinu. Po dvou neúspěšných pokusech milník čeká na revizi; dvě epizody bez důkazu vedou k čekání na ověření. Pokud nelze pokračovat v žádném milníku, automatický běh se pozastaví. Explicitní zadání uživatele má vždy přednost.

Označená chyba hodnoticí infrastruktury, například nedostupný sandbox, se nepočítá jako nedostatek schopnosti. Opačný případ, běhová chyba hodnoceného programu, zůstává skutečným neúspěchem. Toto rozlišení závisí na správném označení chyby důvěryhodným hodnotitelem.

Pokrok používá pouze důkazy přiřazené konkrétnímu milníku. Předchozí nesouvisející opravy ani pouhá změna názvu a popisu stejného workflow nepřidávají body. Kontrolní otisk používá kontrakt, vstupní schéma a kroky; není obecným důkazem sémantické odlišnosti algoritmů. Úspěch cíle, úspěšné spuštění nástroje a splněná metrika milníku zůstávají oddělené. Stav `metric_met` znamená dosažení uvedeného počtu výsledků daného kontraktu; není důkazem zvládnutí celé slovně popsané ambice. Obtížnost je doporučením pro plánování, nikoli naměřenou úrovní inteligence.

Po dosažení všech tří metrik vznikne další generace plánu s vyšším doporučeným stupněm výzvy. Samotné tvrzení modelu o úspěchu úroveň nezvyšuje. Neznámý kontrakt má stav `needs_verifier`; později dodaný důvěryhodný důkaz správného kontraktu lze započítat. Změny hodnotitelů musí dodat řídicí aplikace, model si ověření sám neuděluje.

`status --memory ...` vypisuje i ambice a jejich skutečný pokrok. Přepínač `--no-ambition` vypne plánování ambicí pro dané spuštění. Ambice nemění povolené cesty, dostupné nástroje, počet kroků ani rozpočty. Jsou mechanismem řízení práce, bez tvrzení o pocitech nebo vlastní vůli modelu.

Jde o učení prostřednictvím **paměti zkušeností a skládání pracovních postupů**. Váhy základního modelu se nemění. Návrh nového postupu, jeho úspěšné spuštění a splnění uživatelského cíle jsou tři různé skutečnosti.

## Spuštění

Příkazy spouštějte z kořene projektu ASCENDRA v Pythonu 3.11 nebo novějším. Živé plánování vyžaduje dostupné a přihlášené Codex CLI. Výchozí model je `gpt-6-astra` s reasoning effort `low`; změnit je lze pomocí `--model` a `--effort`. Pro izolované testy je potřeba Linux s funkčním `bwrap` (bubblewrap); chybějící izolace se neobchází.

Samostatná ukázka:

```bash
python -m ascendra.capability_cli demo --output /tmp/ascendra-capability-demo
```

Ukázka proběhne ve dvou epizodách nad malými projekty s funkcí pro aritmetický průměr. Druhá epizoda si sama vybere konkrétní cíl s využitím předchozí zkušenosti. Opravy hodnotí samostatné kontroly, nikoli závěrečná zpráva modelu. Výsledky epizody se mohou použít při dalším plánování; návrhy postupů procházejí zvláštním evaluátorem schopností. Výsledek konkrétního spuštění je nutné číst z jeho evidence, nikoli předpokládat úspěch.

Práce na vlastním projektu s explicitním cílem a povolenou změnou jednoho souboru:

```bash
python -m ascendra.capability_cli grow \
  --project /absolute/path/to/project \
  --memory /absolute/path/to/capability-memory \
  --goal 'Zjisti příčinu selhávajících testů a oprav výpočet průměru.' \
  --allow-write src/statistics.py \
  --cycles 1 \
  --max-steps 14
```

Cesty v `--allow-write` jsou přesné relativní cesty uvnitř projektu. Bez tohoto oprávnění agent nemůže soubory přepisovat. Paměť musí být mimo zkoumaný projekt; CLI odmítne umístění přímo v projektu i v jeho podadresářích. Tím zůstávají zkušenosti, záznamy modelových volání a hodnoticí artefakty mimo soubory dostupné projektovým nástrojům.

Bez `--goal` agent vybere konkrétní další cíl podle dostupných nástrojů a uložených zkušeností:

```bash
python -m ascendra.capability_cli grow \
  --project /absolute/path/to/project \
  --memory /absolute/path/to/capability-memory \
  --cycles 2
```

Výchozí počet cyklů je **1**, výchozí limit je **14 kroků na epizodu**. Cyklus není neomezený běh. Limit kroků není tokenový ani finanční rozpočet: plánování ambicí, cíle a akcí může vyžadovat více modelových volání.

Přehled uložené paměti:

```bash
python -m ascendra.capability_cli status \
  --memory /absolute/path/to/capability-memory
```

Obecný `grow` nemá nezávislého hodnotitele pro libovolný uživatelský cíl. Proto zůstává výsledek cíle **neověřený**, i když model skončí zprávou o úspěchu nebo některé veřejné testy projdou.

## Autonomní tým a sledování běhu

Režim `autonomous` přidává koordinátora, který podle mise a dosavadních výsledků sám vybírá další cíle, rozděluje práci a určuje počet souběžných pracovníků. Po jejich dokončení může naplánovat další kolo nebo běh ukončit. Počet pracovníků je jeho rozhodnutí do limitu `--max-agents`; výchozí limit jsou **4 pracovníci**, **60 modelových volání celkem**, **30 minut** a **8 kroků na pracovní úkol**. Plánování koordinátora se započítává do společného počtu volání. Jde o samostatné rozhodování v programu; tato funkce nedokládá vědomí, vlastní přání ani svobodnou vůli.

Spuštění z terminálu pracovního prostředí:

```bash
ascendra-agent autonomous \
  --project /absolute/path/to/project \
  --output /absolute/path/to/autonomous-run \
  --mission 'Prozkoumej projekt, vyber nejpřínosnější další cíle a rozděl práci podle potřeby.' \
  --allow-write src/statistics.py \
  --max-agents 4 --max-calls 60 --minutes 30
```

Výstupní adresář musí být nový a mimo zkoumaný projekt. Každý pracovník dostane vlastní filtrovanou pracovní kopii; povolené soubory mění pouze v ní. Původní projekt se během běhu nepřepisuje a výsledné změny se automaticky neslučují ani nepublikují. Bez `--allow-write` pracovníci pouze zkoumají projekt, testují a navrhují schopnosti. Rozpočet, oprávnění a možnost zastavení řídí hostitelská aplikace; model je nemůže sám navýšit nebo vypnout. Limit volání není cenový ani přesný tokenový strop.

V druhém terminálu lze sledovat stav a poslední události:

```bash
ascendra-agent watch --output /absolute/path/to/autonomous-run
```

Jednorázový výpis poskytuje `watch --output ... --once`. `Ctrl+C` v příkazu `watch` ukončí pouze sledování. Zastavení samotného autonomního běhu se vyžádá samostatným příkazem:

```bash
ascendra-agent stop --output /absolute/path/to/autonomous-run
```

Příkaz vytvoří značku `STOP`; řídicí proces ji zpracuje a aktualizuje stav. Ověřte konečný stav příkazem `watch --once`. Soubor `status.json` obsahuje průběžný přehled, `events.jsonl` události a výstupní adresář uchovává podklady jednotlivých pracovníků. Terminálové příkazy se spouštějí v daném pracovním prostředí; samy neotevírají terminálové okno v chatu ani veřejné webové rozhraní.

Pracovníci sdílejí paměť v `output/memory`; pozdější rozhodnutí mohou použít dříve ověřené postupy. Každá pracovní kopie přesto začíná z původního snímku projektu, takže změny jiného pracovníka nepřebírá automaticky.

Výstupy pracovníků a projektové testy jsou pozorování. Samostatně ověřené schopnosti mají vlastní evidenci; obecný úspěch zvolené mise zůstává bez nezávislého hodnotitele neověřený. Koordinátor dostává výsledky pro další plánování, ale tvrzení pracovníka o úspěchu se tím nemění na důkaz správnosti. Počet `completed_tasks` označuje dokončené epizody pracovníků, nikoli nezávisle prokázané splnění cílů.

## Návrh, ověření a použití schopnosti

1. Model navrhne popis, motivaci, kritéria úspěchu a posloupnost nejvýše 16 kroků ze známých nástrojů. Postup může mít vstupní schéma a používat parametry `$input.nazev`.
2. Paměť uloží návrh se stavem `proposed`. Model nemůže prohlásit návrh za ověřený; pole `verified` se odmítá a vlastní `status` návrhu nerozhoduje.
3. Řídicí vrstva předá návrh důvěryhodnému evaluátoru. Podporovaný kontrakt musí projít úplnou sadou nezávislých fixtures. Evidence obsahuje identitu kontraktu a verze evaluátoru, hash návrhu, hashe fixtures a výsledky.
4. Teprve stav `verified` zpřístupní postup v dalších rozhodnutích jako `capability:<id>`. Použití postupu zachovává původní oprávnění projektu; návrh ani ověření nepřidávají nové nástroje nebo zápisová oprávnění.

Současné kontrakty `python_test_diagnosis` a `python_project_inspection` ověřují skutečné čtení zdroje, hledání textu a spuštění parametrizovaných testů `unittest` na **třech nezávislých fixtures**. Kontrolují zachování skutečných výsledků včetně selhání a chyb testů. Neověřují správnost vysvětlení příčiny ani obecnou schopnost opravovat chyby.

Úspěšně spuštěný nástroj může správně vrátit neúspěšné testy. Taková diagnostika je platný výsledek nástroje, nikoli splněný cíl. Nula objevených testů se nepovažuje za úspěšnou testovací sadu. Neznámý kontrakt nebo nevyhodnotitelný návrh zůstává `needs_evaluation`; skutečně neúspěšné ověření má stav `failed`.

## Rozsah nástrojů a evidence

Katalog obsahuje `list_files`, `read_file`, `search_text`, `run_tests` a `write_file`. Neposkytuje libovolný shell, instalaci závislostí, síťový nástroj ani nasazování služeb. Testy běží systémovým Pythonem v samostatném sandboxu bez sítě nad filtrovanou kopií projektu pouze pro čtení. Omezení sítě se týká testovacího sandboxu; samotná komunikace s poskytovatelem modelu síť používá.

Přístup k souborům je omezen na veřejné cesty projektu, se zákazem úniků přes relativní cesty a symlinky a s filtry soukromých cest. Zápisy musí odpovídat explicitně povoleným cestám. Postupy jsou deklarativní posloupnosti existujících nástrojů. Souběžné pracovníky vytváří koordinátor režimu `autonomous`; pracovník nemůže tento limit obejít rekurzivním vytvářením dalších agentů.

Paměť odděluje úspěch spuštění nástroje, ověřený výsledek cíle a dosud neověřené epizody. Pro další plánování poskytuje omezené souhrny výsledků, konkrétní chyby a dostupné schopnosti. Preference nástrojů vycházejí z pozorované úspěšnosti jejich spuštění; neprokazují jejich kauzální vliv na splnění cíle.

Záznamy se přidávají do atomicky ukládaného žurnálu s kontrolními součty, řetězem hashů a procesovým zámkem. To detekuje poškození; nejde o ochranu proti útočníkovi, který může přepsat celý žurnál a přepočítat hashe. Metody pro zápis výsledků důvěryhodného evaluátoru nejsou nástroji modelu.

## Moduly

| Soubor | Odpovědnost |
| --- | --- |
| `ascendra/capability_agent.py` | Výběr cíle a akcí, limity epizody, návrhy a spuštění ověřených postupů. |
| `ascendra/capability_ambition.py` | Trvalé ambice, milníky, přiřazení důkazů a adaptace další výzvy. |
| `ascendra/capability_tools.py` | Katalog nástrojů, přístup k souborům a izolované testy. |
| `ascendra/capability_memory.py` | Trvalé epizody, výsledky cílů, návrhy a evidence ověření. |
| `ascendra/capability_evaluator.py` | Nezávislé kontrakty a kontrola skutečných výsledků postupů. |
| `ascendra/capability_objective.py` | Nezávislé ověření výpočtu průměru v ukázce. |
| `ascendra/capability_autonomy.py` | Autonomní koordinátor, souběžní pracovníci, rozpočet a průběžná evidence. |
| `ascendra/capability_cli.py` | Příkazy `demo`, `grow`, `status`, `autonomous`, `watch` a `stop`. |

Tato funkce představuje samostatný experimentální agentní režim. Není výsledkem potvrzovací studie zlepšení na nových úlohách a nemění historické výsledky ani zmrazené běhy V4/HARD.
