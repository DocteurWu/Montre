# Montre — piloter une montre IDO **ID205L** depuis son PC

> ⚠️ **Ce projet est fait pour UNE montre précise : la ID205L (fabricant IDO / Shenzhen DO Intelligent Technology), firmware v36.**
> Elle est aussi vendue sous d'autres marques (Letsfit, etc.) et s'utilise normalement avec l'appli **VeryFit Pro**.
> Une autre montre « connectée chinoise », même identique en apparence, utilise très probablement un autre protocole : **ce code ne marchera pas dessus.**

## Comment savoir si c'est ta montre

| Vérification | Valeur attendue |
|---|---|
| Nom Bluetooth | `ID205L` |
| Écran « À propos » de la montre | `V36.0.0` + une adresse MAC |
| Dos du boîtier | `FCC ID: 2AHFT228` |
| Appli officielle | VeryFit Pro (`com.veryfit2hr.second`) |
| Service Bluetooth | `0AF0` (caractéristiques `0AF1`, `0AF2`, `0AF6`, `0AF7`) |

Pour vérifier en 15 secondes : `python outils/montre_ble.py scan`. La montre doit apparaître avec le nom `ID205L`.

## Ce que ça fait

Tout passe par **Bluetooth Low Energy**, depuis le PC, sans toucher au firmware de la montre.

| Fonction | État |
|---|---|
| Afficher **n'importe quel message** (titre ≤ 30 car., texte ≤ 150) | ✅ testé |
| Afficher un **faux appel entrant** (nom + numéro) | ✅ testé |
| **Boutons de la montre → PC** : les 4 touches de l'écran *Musique* (lecture, pause, précédent, suivant) déclenchent une action au choix sur le PC | ✅ testé |
| Mettre à l'heure, lire la batterie et le firmware | ✅ testé |
| Couper : rappel « assis trop longtemps », anti-perte, météo ; régler « ne pas déranger », lever du poignet, sports du menu | ✅ accepté par la montre |
| Transférer les **notifications du téléphone Android** (via adb) vers la montre | ✅ testé |
| **Serveur MCP** : Claude (ou tout client MCP) pilote la montre | ✅ testé |
| Intensité de mouvement (accéléromètre) en mode test usine | ⚠️ marche, mais la montre redémarre en sortant du mode test |
| Historique pas / cardio / sommeil | ⚠️ reçu, format pas entièrement décodé |
| Balayages, autres écrans, appui pendant un appel → PC | ❌ la montre ne les transmet pas |
| Retirer des écrans du menu, flux brut des capteurs | ❌ impossible sans changer le firmware (non couvert ici) |

**Une seule connexion Bluetooth à la fois** : si VeryFit Pro est connectée sur le téléphone, le PC ne voit pas la montre (et inversement). Le Bluetooth de la montre est aussi coupé pendant la charge.

## Installation

```bash
pip install -r requirements.txt
```

Windows 10/11, macOS ou Linux avec Bluetooth LE (testé sous Windows 11, Python 3.13).

Optionnel : si plusieurs ID205L sont à portée, donne l'adresse de la tienne (écran « À propos » de la montre) :

```bash
set MONTRE_MAC=AA:BB:CC:DD:EE:FF      # Windows (cmd)
export MONTRE_MAC=AA:BB:CC:DD:EE:FF   # macOS / Linux
```

## Utilisation

### Interface web

```bash
python interface.py
```

Ouvre http://127.0.0.1:8765 : messages libres et rapides, faux appel, état, réglages, **configuration des boutons** et journal.
Sur la montre, ouvre l'écran **Musique** : ses 4 touches lancent l'action choisie (afficher l'heure, la batterie, un message, ou **lancer une commande sur le PC** dont le résultat s'affiche sur la montre).
L'interface n'écoute que sur `127.0.0.1` et refuse les requêtes venant d'autres sites.

### Serveur MCP (Claude)

```bash
claude mcp add montre -s user -- python /chemin/vers/mcp_montre.py
```

Outils : `envoyer_message`, `faux_appel`, `raccrocher`, `etat_montre`, `mettre_a_l_heure`, `regler`, `derniers_boutons`, `configurer_bouton`.
Si l'interface tourne, le serveur MCP passe par elle (une seule connexion Bluetooth possible) ; sinon il se connecte lui-même.

### Notifications du téléphone → montre

```bash
python pont_telephone.py
```

Téléphone Android branché en **débogage USB** (`adb devices` doit le lister). Filtres `IGNORER` / `SEULEMENT` en haut du fichier.

### En Python

```python
import asyncio
from ido import Watch

async def main():
    async with Watch() as w:
        await w.set_time()
        await w.message("Titre", "Le texte que je veux")
        print(await w.battery())

asyncio.run(main())
```

## Fichiers

| Fichier | Rôle |
|---|---|
| `ido.py` | Pilote : classe `Watch` (toutes les commandes) |
| `service.py` | Connexion partagée, reconnexion auto, actions des boutons |
| `interface.py` + `interface.html` | Interface web locale |
| `mcp_montre.py` | Serveur MCP |
| `telecommande.py` | Boutons → fonctions Python, sans interface |
| `pont_telephone.py` | Notifications Android → montre |
| `outils/montre_ble.py` | Scan, exploration GATT, console hexa |
| `outils/ecoute.py` | Affiche tout ce que la montre envoie |
| `outils/capteurs.py` | Accéléromètre (mode test usine) |
| `outils/sonde.py` | Balaye une plage de commandes |
| `outils/analyse_logcat.py` | Décode les trames écrites par VeryFit Pro dans logcat |
| `outils/capture_ble.py` | Décode un journal HCI Bluetooth Android (`btsnoop_hci.log`) |

## Protocole (ID205L, firmware 36)

Trame de **20 octets** : `[commande, clé, données…]` écrite sur `0AF6`, réponse en notification sur `0AF7`.
Historique santé : écriture sur `0AF1`, réponses sur `0AF2`. Entiers en little-endian. **Aucune authentification.**

| Cmd | Rôle | Clés vérifiées sur cette montre |
|---|---|---|
| `02` | Lire | `01` infos, `02` fonctions, `03` heure, `04` MAC, `05` batterie, `A0` données live |
| `03` | Régler | `01` heure, `20` rappel assis, `21` anti-perte, `25` mode cardio, `28` lever poignet, `29` ne pas déranger, `2A` musique (`AA 55` = on), `2B` paysage, `2D` météo, `2E` sports, `30` notifs |
| `05` | Messages | `01` appel, `02` fin d'appel, `03` message (paquets : total, n°, 16 octets) |
| `06` | Contrôle | `01` écran musique (`00 00 00 00`) |
| `07` | Montre → PC | `01 01` lecture, `01 02` pause, `01 04` précédent, `01 05` suivant |
| `08` | Historique (sur `0AF1`) | `01` début, `03` activité, `04` sommeil, `07` cardio, `02` fin |
| `AA` | Mode test usine | `01` entrer, `03` accéléromètre, `02` sortir (redémarre) |

Comment ça a été trouvé :
- la structure générale vient du SDK open source d'IDO [orangebrush/angelfit](https://github.com/orangebrush/angelfit) (ancienne version du protocole) et de l'article [Bad Smart Watch Auth](https://sprocketfox.io/xssfox/2025/02/09/ido/) ([xssfox/idowatch](https://github.com/xssfox/idowatch)) ;
- chaque commande a ensuite été testée sur la montre ;
- l'activation des boutons (`03 2A AA 55` puis `06 01`) a été relevée dans les journaux Android de VeryFit Pro, qui écrit chaque trame en clair (`TX :` / `RX :`), avec `outils/analyse_logcat.py`.

## Avertissement

Projet personnel, non affilié à IDO ni à VeryFit. Fourni tel quel, à utiliser avec ta propre montre.
