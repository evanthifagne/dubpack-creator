# DubPack Creator

Outil local de création de **dub packs** pour *The Choicer Voicer*.

[![Télécharger](https://img.shields.io/github/v/release/evanthifagne/dubpack-creator?label=t%C3%A9l%C3%A9charger&style=for-the-badge)](https://github.com/evanthifagne/dubpack-creator/releases/latest)
[![Licence MIT](https://img.shields.io/badge/licence-MIT-blue?style=for-the-badge)](LICENSE)

Tu déposes un **lien YouTube** ou un **fichier MP4**, l'outil transcrit les
dialogues avec **Whisper** (en local, sur ta machine), **détecte
automatiquement les personnages** en regroupant les voix, et te laisse tout
corriger dans un éditeur web avant d'exporter un pack prêt à déposer dans le
jeu.

Fonctionne sur **Windows** et **macOS**. Rien ne part sur internet : le seul
accès réseau est le téléchargement de la vidéo (si tu donnes un lien) et celui
du modèle Whisper au premier lancement.

---

## Installation

### Windows — l'installeur (recommandé)

**[⬇ Télécharger `DubPackCreator-Setup-<version>.exe`](https://github.com/evanthifagne/dubpack-creator/releases/latest)**

1. Lance l'installeur. Aucun droit administrateur, aucune installation de
   Python : **tout est fourni**, ffmpeg compris.
   > SmartScreen peut afficher « Windows a protégé votre ordinateur » car
   > l'installeur n'est pas signé : clique **Informations complémentaires →
   > Exécuter quand même**.
2. À la fin, coche « Lancer DubPack Creator ». Le navigateur s'ouvre sur une
   page de démarrage : le premier lancement télécharge les composants de
   transcription (quelques minutes, progression affichée), puis l'application
   apparaît. Les lancements suivants sont immédiats.
3. Ensuite, lance l'application depuis le raccourci du Bureau ou le menu
   Démarrer. Pas de fenêtre noire : tout vit dans le navigateur. Pour
   arrêter : roue crantée → **Quitter DubPack Creator**.

L'application s'installe dans `%LOCALAPPDATA%\DubPackCreator`. Tes projets,
modèles et réglages y restent, même après une désinstallation.

> **Tu utilisais l'ancienne version ZIP ?** Installe simplement l'installeur.
> Pour retrouver tes anciens projets, copie le dossier `projects` de l'ancien
> dossier vers `%LOCALAPPDATA%\DubPackCreator\projects`.

### macOS — l'application

**[⬇ Télécharger `DubPackCreator-<version>-macOS.dmg`](https://github.com/evanthifagne/dubpack-creator/releases/latest)** *(Apple Silicon)*

1. Ouvre le `.dmg` et glisse **DubPack Creator** dans **Applications**.
2. Premier lancement : **clic droit → Ouvrir** (application non signée par
   Apple), puis confirme. Les fois suivantes, un double-clic suffit.
3. Le navigateur s'ouvre sur la page de démarrage ; le premier lancement
   installe les composants (quelques minutes). ffmpeg est fourni — rien à
   installer avec Homebrew.

Les données vivent dans `~/Library/Application Support/DubPackCreator`.

> Rappel : le jeu n'existe pas sur macOS. Tu peux préparer tes packs ici, puis
> les transférer sur le PC Windows (export « Archive ZIP »).

## Mises à jour automatiques

Plus besoin de retélécharger l'application : elle vérifie discrètement au
démarrage si une nouvelle version existe (une simple lecture des releases
GitHub — rien ne s'installe sans ton accord).

- Quand une version est disponible, un badge apparaît en haut de l'interface.
- Roue crantée → **Application** → **Installer et redémarrer** : l'application
  télécharge la nouvelle version (~150 Ko), vérifie son empreinte SHA-256,
  l'applique et redémarre toute seule. La page se recharge automatiquement.
- Tes projets, modèles et réglages ne sont jamais touchés. Si une mise à jour
  ne démarre pas, l'application **revient automatiquement à la version
  précédente**.
- Réglable : la vérification automatique se désactive dans les réglages, et le
  bouton **Rechercher les mises à jour** interroge GitHub à la demande.

## Installation alternative (ZIP + scripts)

Pour ceux qui préfèrent un dossier portable ou la ligne de commande :
`DubPackCreator-Windows-<version>.zip` contient les scripts historiques.
Il faut **Python 3.10+** ([python.org](https://www.python.org/downloads/),
cocher « Add Python to PATH »).

1. Décompresse le ZIP, double-clique **`INSTALLER.bat`** (une seule fois).
2. Lance avec **`DEMARRER.bat`**. Les mises à jour automatiques fonctionnent
   aussi dans ce mode.

macOS / ligne de commande : `python3 run.py` depuis le dossier du projet
(`./start.command` sur Mac). Options : `--port 8888`, `--no-browser`,
`--install-extras` (Demucs + empreintes vocales).

> **ffmpeg doit contenir `libtheora`** (le jeu tourne sous Godot, qui ne lit
> que l'Ogg Theora). L'installeur et l'application le fournissent. En mode
> ZIP : Windows le télécharge tout seul ; macOS utilise le ffmpeg installé par
> pip, qui convient aussi.

## Télécharger les modèles à l'avance

Roue crantée → **Modèles de transcription**. Chaque modèle indique sa taille,
ce qu'il vaut, et s'il est déjà présent :

| Modèle | Taille | Pour quoi |
|---|---|---|
| `tiny` | 75 Mo | Très rapide, qualité approximative. Pour dégrossir. |
| `base` | 145 Mo | Rapide, correct sur un son net. |
| `small` | 480 Mo | **Recommandé** — le bon compromis. |
| `medium` | 1,5 Go | Nettement plus précis, environ 3× plus lent. |
| `large-v3` | 3,1 Go | Le plus précis, lent sans carte graphique dédiée. |
| `large-v3-turbo` | 1,6 Go | Précision proche de large-v3, beaucoup plus rapide. |

Le téléchargement affiche sa progression et s'annule proprement. Sans cette
étape, le modèle se télécharge tout seul au premier usage — c'est juste plus
long à ce moment-là.

## Comment ça marche

1. **Dépose ta vidéo** — fichier glissé, ou lien collé (YouTube et tous les
   sites gérés par yt-dlp).
2. **Règle la transcription** — modèle Whisper, langue, nombre de voix,
   longueur maximale d'une réplique. En cas de doute, laisse tout en
   automatique ; `small` est un bon compromis.
3. **Clique « Générer le dub pack »**. L'outil télécharge la vidéo, en extrait
   l'audio, transcrit, découpe le texte en répliques jouables (aux silences et
   à la ponctuation), regroupe les voix et propose des noms de personnages
   repérés dans les dialogues.
4. **Corrige dans l'éditeur** :
   - la timeline montre la forme d'onde et une barre colorée par réplique ;
   - chaque réplique s'écoute, se recale, se coupe (`✂`), se fusionne (`⤵`) ou
     se désactive ;
   - renomme les personnages une fois : le nom se propage partout ;
   - `📷` capture l'image courante de la vidéo comme portrait d'un personnage ;
   - raccourcis : `Espace` lecture/pause, `←`/`→` (+`Maj`) navigation,
     `J`/`K` réplique précédente/suivante.
5. **Onglet Export** — génère éventuellement le fond sonore, vérifie les
   avertissements, puis exporte. Tu récupères un dossier **et** un ZIP.

## Les sons non parlés (cris, souffles, impacts)

Whisper transcrit de la parole. Un cri dans une bagarre, un souffle, un coup : ce
n'est pas du texte, et la détection d'activité vocale les écarte activement.
Sans traitement particulier, ces sons **disparaissaient** du pack — or dans une
scène d'action, ce sont justement eux qu'on veut doubler.

L'option **Repérer les sons non parlés** (activée par défaut) analyse les
passages sonores que la transcription n'a pas couverts et les ajoute comme
répliques, avec un libellé proposé :

| Libellé | Ce qui le déclenche |
|---|---|
| `[cri]` | voisé, hauteur élevée |
| `[grognement]` | voisé, hauteur basse ou moyenne |
| `[impact]` | attaque sèche suivie d'une extinction rapide |
| `[souffle]` | non voisé et tenu |
| `[son]` | le reste |

Ces répliques sont **repérables d'un coup d'œil** : pastille bleue dans la liste,
hachures sur la timeline, texte en italique. Le libellé est un point de départ —
remplace-le par ce que tu veux voir affiché dans le jeu (`[il hurle]`,
`[grognement de douleur]`…). Le bouton **Retirer les sons** les supprime tous
d'un coup si la détection a été trop bavarde.

La classification reste grossière et l'assume : un choc grave peut passer pour un
grognement. Ce qui compte, c'est que le son **soit là**, au bon instant, avec la
bonne durée — le libellé, tu le corriges en deux secondes.

Un son non parlé ne sert jamais à définir un personnage : il est rattaché à la
voix la plus proche, sans peser sur la détection des voix.

## Pendant le traitement

La fenêtre de suivi montre l'avancement, le **temps écoulé** et une **estimation
du temps restant** dès que le rythme est mesurable. Quand une étape n'a pas
d'avancement à afficher — le chargement du modèle, par exemple — la barre passe
en animation continue pour montrer que ça travaille.

**« Continuer sans attendre »** ferme la fenêtre sans rien interrompre : la tâche
poursuit et reste suivie en bas à gauche, où un clic ramène le détail. Tu peux
donc naviguer, éditer un autre pack, ou en lancer d'autres.

Les tâches lourdes (transcription, encodage, séparation des voix) se font **une à
la fois**, dans l'ordre de lancement : deux transcriptions simultanées ne feraient
que se ralentir. Tu peux donc enchaîner cinq vidéos et laisser tourner. Chaque
tâche en attente indique son rang, et peut être annulée avant démarrage.

Si tu rafraîchis ou rouvres la page, le suivi se reprend tout seul : les tâches
vivent dans le serveur, pas dans le navigateur.

**Annuler** interrompt les programmes en cours (ffmpeg, yt-dlp, Demucs) au lieu
d'attendre poliment la fin de l'étape : compte deux à trois secondes. La fenêtre
indique ce qui reste à arrêter, et un second appui force la coupure. Seule
exception honnête : le téléchargement d'un modèle ne peut pas être interrompu en
cours de route — la fenêtre le dit explicitement.

## Où atterrit le pack (onglet Export)

Trois destinations, au choix :

**Directement dans le jeu** — clique **Détecter le jeu**. L'outil balaie les
emplacements habituels (dossier de l'app itch.io, données utilisateur Godot,
Téléchargements, Bureau, Documents, `C:\Games`, Program Files…) et te propose
les installations trouvées, avec les indices qui l'ont convaincu. Tu choisis,
et le pack est écrit dans `packs_voice` : c'est jouable immédiatement. Le
dossier `packs_voice` est créé s'il n'existe pas, et un pack de même nom n'est
jamais remplacé sans que tu aies coché l'option.

Si la détection ne trouve rien : dans le jeu, **Modpack Guides → Dub Mode Packs
→ Open Folder**, copie le chemin depuis l'Explorateur et colle-le dans le champ
**Chemin du jeu**. L'outil s'en souvient pour les fois suivantes.

**Dans un dossier de mon choix** — le Bureau, une clé USB, un dossier partagé.

**Une archive ZIP** — tu choisis le dossier où elle est déposée (Bureau, clé
USB…). Laissé vide, le ZIP reste dans le dossier de l'outil avec un bouton de
téléchargement.

## Installer le pack à la main

1. Décompresse le ZIP (ou prends directement le dossier exporté).
2. Copie le dossier du pack dans le dossier **`packs_voice`** du jeu.
   Les dub packs vont bien dans `packs_voice`, pas dans un dossier séparé.
3. Vérifie qu'il n'y a **pas de niveau de dossier en trop** :
   `packs_voice/Mon Pack/dub_video.ogv` doit exister — et non
   `packs_voice/Mon Pack/Mon Pack/dub_video.ogv`.
4. Lance le jeu et sélectionne le pack en mode Dub.

## Ce qui est exporté

Structure calquée sur un dub pack de la communauté qui fonctionne en jeu :

```
Mon Dub Pack/
├── _pack_info.ini                  titre, icône, auteurs, readme
├── icon.png                        vignette du pack
├── dub_video.ogv                   vidéo de référence (Theora + Vorbis)
├── _backing_track.mp3              fond sonore sans les voix (facultatif)
├── 01_lucie_marco-tu-as-vu.ogg     audio d'origine de la réplique
├── 01_lucie_marco-tu-as-vu.png     image affichée pendant la séquence
├── 01_lucie_marco-tu-as-vu.txt     métadonnées de la réplique
├── 02_marco_oui-lucie.ogg
├── 02_marco_oui-lucie.png
└── 02_marco_oui-lucie.txt
```

Chaque réplique produit **trois** fichiers de même nom : l'audio, l'image et les
métadonnées, au format ConfigFile de Godot :

```ini
[data]

caption="Marco, tu as vu ce qui s'est passé hier soir ?"
image="01_lucie_marco-tu-as-vu.png"
dub_timestamps=[0.340]
dub_characters=["Lucie"]
```

- `caption` — le sous-titre affiché ;
- `image` — l'image montrée pendant la séquence. **C'est elle qui manquait** :
  sans elle, le jeu joue le son sans rien afficher. Elle est prise au milieu de
  la réplique, là où le personnage est en train de parler, et à la taille exacte
  de la vidéo exportée ;
- `dub_timestamps` — l'instant, en secondes, où la réplique se déclenche ;
- `dub_characters` — le personnage qui parle, ce qui permet au joueur de filtrer ;
- `tags`, `dub_only` — ajoutés seulement si tu les renseignes.

Le pack ne contient **aucun autre fichier** : depuis que les métadonnées sont en
`.txt`, un fichier texte égaré pourrait être pris pour la description d'une
réplique.

Les clips sont en `.ogg` là où les packs de la communauté utilisent `.mp3`. Les
deux sont lus par le jeu — l'`.ogg` a été vérifié en jeu, et il est plus léger à
qualité égale.

## Fond sonore : sépare les voix

Le jeu joue un `_backing_track.mp3` derrière ta voix. **Il doit contenir la
musique et les bruitages sans les dialogues.**

Ce n'est pas une supposition : j'ai analysé un dub pack de la communauté qui
fonctionne. Son fond sonore a un niveau dix fois plus faible que l'audio
d'origine et n'est presque pas corrélé avec lui — les voix y ont bien été
retirées. L'éditeur de référence le dit aussi noir sur blanc : il sépare les
voix avec Demucs.

**Utilise donc « Séparer les voix (Demucs) ».** L'option « Utiliser l'audio
d'origine » n'est qu'un repli si tu n'as pas Demucs : le fond sonore contiendra
alors les dialogues originaux, et tu t'entendras doubler par-dessus la voix
d'origine.

Demucs s'installe depuis **Réglages → Modules optionnels** (~2 Go, PyTorch).

## Qualité de la détection des personnages

Le regroupement des voix repose sur des empreintes vocales, puis sur un
regroupement hiérarchique. Le type d'empreintes change tout.

Mesuré en faisant passer la vidéo d'un dub pack de la communauté dans l'outil,
puis en comparant l'attribution des personnages à celle du pack fait à la main :

| Empreintes | Bonnes attributions |
|---|---|
| maison (MFCC + hauteur, sans dépendance) | **55 %** — le hasard |
| **ECAPA-TDNN** (module optionnel) | **82 à 86 %** |

Sur des voix nettement différentes, les deux marchent. Sur du vrai son de film,
où la musique et les bruitages se mêlent aux voix, seul ECAPA tient. **Installe-le**
depuis Réglages → Modules optionnels ; il vient avec Demucs, et les deux
partagent PyTorch.

Il reste des erreurs : compte une réplique sur cinq à réattribuer, d'un menu
déroulant. C'est pour ça que l'outil est un éditeur.

Pour améliorer encore :

- fixe le **nombre de personnages** au lieu de laisser « auto », puis
  **Retranscrire** ;
- corrige les répliques restantes à la main.

### Les noms de personnages

L'outil propose des noms trouvés dans les dialogues, mais ne renomme
automatiquement que si les indices concordent : le nom doit apparaître au moins
deux fois, être employé en apostrophe, et figurer ailleurs qu'en début de phrase.

Sans cela il laisse « Personnage 1 » et te montre les noms candidats. C'est
volontaire : sur une transcription approximative, il inventait des noms à partir
de mots mal reconnus, et ces noms partaient dans `dub_characters` et dans les
noms de fichiers.

## Où sont mes fichiers

Dans le dossier de données de l'application — `%LOCALAPPDATA%\DubPackCreator`
sous Windows, `~/Library/Application Support/DubPackCreator` sous macOS, le
dossier du projet en mode ZIP :

- `projects/<date>/` — un dossier par projet : vidéo source, audio de travail,
  `project.json` (tes modifications, sauvegardées automatiquement) ;
- `projects/<date>/export/` — le dossier du pack et son ZIP ;
- `.cache/models/` — les modèles Whisper téléchargés (supprimable) ;
- `code/` — le code de l'application, remplacé par les mises à jour ;
- `settings.json` — le dossier du jeu et la destination d'export mémorisés.

Supprimer un projet depuis l'accueil (🗑) efface tout son dossier.

## Quand une tâche échoue

Une fenêtre s'ouvre avec : le message, **ce qu'il y a à faire** quand la cause
est reconnue (ffmpeg absent, refus de YouTube, disque plein, pack existant…), et
un repli **Détails techniques** contenant le contexte complet — étape atteinte,
avancement, durée, version de Python, et la trace de l'erreur.

Le bouton **Copier le rapport** met tout ça dans le presse-papier : c'est ce
qu'il faut coller pour demander de l'aide.

Les erreurs restent consultables après coup : **Diagnostic → Dernières tâches**,
puis « voir le détail ».

## Le panneau Diagnostic

Bouton **Diagnostic** en haut à droite (ou clic sur les pastilles de couleur).
Il montre, sans deviner : le chemin exact de ffmpeg utilisé, les encodeurs
disponibles, le contenu du dossier `bin/`, le repli `imageio-ffmpeg`, le moteur
de transcription, Demucs, le sélecteur de dossier, la version de Python.

Quand quelque chose manque, il propose la réparation :

- **Installer ffmpeg automatiquement** (Windows) — télécharge la bonne build et
  la place dans `bin/`, sans redémarrer l'outil ;
- **Installer Demucs** — pour le fond sonore, ~2 Go, nécessite un redémarrage.

Si ffmpeg manque au démarrage, ce panneau s'ouvre tout seul.

> **Antivirus** : si ffmpeg disparaît de `bin/` après installation, c'est
> presque toujours une mise en quarantaine — un gros exécutable non signé est un
> faux positif classique. Autorise le dossier `bin/` de l'outil.

## En cas de problème

| Symptôme | Cause probable |
|---|---|
| Badge **ffmpeg** rouge | ffmpeg absent du PATH → l'installer, ou déposer le binaire dans `bin/` |
| Badge **Theora** rouge | build ffmpeg incomplète → Diagnostic → « Installer ffmpeg automatiquement » |
| « ffmpeg n'est pas installé » | Diagnostic → « Installer ffmpeg automatiquement ». Si ça échoue, l'antivirus a probablement mis `bin/ffmpeg.exe` en quarantaine |
| **Demucs absent** dans le bandeau | normal, c'est facultatif : Diagnostic → « Installer Demucs » si tu veux le fond sonore |
| « Aucune parole détectée » | vidéo sans dialogues, ou mauvaise langue forcée → réessaie en détection automatique ou avec un modèle plus grand |
| Transcription lente | normal en CPU : commence par `tiny`/`base` pour dégrossir, puis repasse en `small`/`medium` |
| Le pack n'apparaît pas dans le jeu | un dossier en trop dans `packs_voice`, ou `dub_video.ogv` manquant |
| Le jeu n'est pas détecté | dans le jeu : Modpack Guides → Dub Mode Packs → Open Folder, puis colle le chemin |
| « Un pack du même nom existe déjà » | coche « Remplacer un pack du même nom » avant d'exporter |
| « ffmpeg is not installed » en collant un lien | corrigé en v1.0.3 : yt-dlp ne cherchait ffmpeg que dans le PATH, jamais dans `bin/`. Mets l'outil à jour |
| Un lien vidéo échoue | panneau Diagnostic → **Mettre yt-dlp à jour** : les sites changent souvent |
| Le port est déjà pris | l'outil en choisit un autre automatiquement — lis l'URL affichée dans la console |

## Notes

Le format de pack implémenté ici suit la documentation publique de *The Choicer
Voicer* (dossier dans `packs_voice`, `dub_video.ogv` obligatoire,
`_backing_track.ogg` facultatif, un `.ini` par clip portant `caption`,
`dub_timestamps` et `dub_characters`). Si une version du jeu change ces
conventions, il suffit d'ajuster `app/dubpack.py`.

Cet outil est un projet indépendant, écrit de zéro. Il n'est affilié ni au jeu
ni à ses auteurs, et ne reprend aucun code du
[dépôt de référence](https://github.com/Loganrithm/choicervoicerdubpackeditor)
(qui ne publie que son README et une licence interdisant les dérivés).

Sous licence MIT — voir [LICENSE](LICENSE). Les composants tiers et leurs
licences sont listés dans [THIRD-PARTY.md](THIRD-PARTY.md).

Respecte les droits des vidéos que tu utilises et les règles de la communauté
du jeu.
