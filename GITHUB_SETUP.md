# GitHub a vývojové prostředí

Zdrojový kód je nyní přímo v repozitáři. Historické soubory v `cloud_bundle/` se automaticky nerozbalují; `bootstrap_cloud.py` pouze kontroluje aktuální checkout. Tím se stará verze nemůže přepsat přes novou implementaci.

## Automatické kontroly

Workflow **CI** běží na push do `main`, pull request do `main` i ruční spuštění. Tím nezdvojuje kontroly téže změny při každém push do pracovní větve. Ubuntu 24.04 poskytuje systémový Python 3.12, který používá i sandbox. Workflow instaluje `bubblewrap`, ověřuje skutečnou izolaci, sestaví balíček, spustí celou testovací sadu a zkontroluje obě instalovaná CLI. Log testů se uchovává 14 dní.

Token workflow má pouze `contents: read`. CI nepotřebuje žádné repository secrets a neprovádí modelová volání. Actions jsou připnuté na konkrétní commity a Dependabot měsíčně navrhuje jejich aktualizace. Pro uživatelské namespaces workflow upravuje příslušný AppArmor sysctl pouze na dočasném runneru.

## Nastavení repozitáře

Pro spuštění musí být v **Settings → Actions → General** povolené GitHub Actions včetně `actions/checkout` a `actions/upload-artifact`. Konfigurace workflow sama vynucuje pouze čtení obsahu repozitáře. Zapnutí Actions nebo změna globálních oprávnění vyžaduje administrativní oprávnění připojené GitHub aplikace, nikoli jen administrátorskou roli uživatele.

Soubor `.github/branch-protection.json` obsahuje požadované nastavení `main`: aktuální větev a úspěšný check `Python 3.12 and sandbox tests`, vyřešené diskuse, zákaz force push a smazání větve. Nevyžaduje cizí schválení, takže funguje i v repozitáři jediného vývojáře. Soubor sám ochranu neaktivuje. Účet s přístupem k administrativnímu API ji může aplikovat:

```bash
gh api --method PUT repos/HappyMistake64/ASCENDRA/branches/main/protection \
  --input .github/branch-protection.json
```

Tento příkaz nahrazuje konfiguraci ochrany větve. Před opakovaným použitím porovnejte případná novější pravidla v nastavení GitHubu. Ochrana veřejné větve je dostupná i bez placeného tarifu; GitHub přesto může vyžadovat dodatečné oprávnění konkrétní aplikace.

## Lokální a Codex Cloud instalace

Použijte Linux se systémovým Pythonem alespoň 3.11 a funkčním `bubblewrap`. Doporučený základ je Ubuntu 24.04. Jednorázová instalace systémových závislostí:

```bash
sudo apt-get update
sudo apt-get install -y bubblewrap python3-venv
bash scripts/setup.sh
source .venv/bin/activate
python -m unittest discover -s tests -v
```

V Codex Cloud lze po instalaci systémových závislostí použít `bash scripts/setup.sh` jako setup command. Skript neobchází chybějící OS sandbox; pokud host zakazuje uživatelské namespaces, musí je podporovat konfigurace tohoto prostředí.

Pro živé běhy musí být samostatně nainstalované a přihlášené oficiální Codex CLI. Přístup k modelu `gpt-6-astra` musí poskytovat přihlášený účet. Živé demonstrace byly provedeny s `codex-cli 0.159.0-alpha.3`; adaptér používá podporu strukturovaných odpovědí a vypnutí nástrojů tohoto rozhraní. Přihlašovací soubory ani osobní tokeny nepatří do repozitáře nebo do logů CI. CI nepřihlašuje model za uživatele.

Podrobnosti: [CAPABILITY_AGENT.md](CAPABILITY_AGENT.md), [SUBSCRIPTION_RUN.md](SUBSCRIPTION_RUN.md).
