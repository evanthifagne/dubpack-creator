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

## Installation rapide sur Windows

**[⬇ Télécharger la dernière version](https://github.com/evanthifagne/dubpack-creator/releases/latest)**

Décompresse le ZIP où tu veux, puis :

1. Double-clique **`INSTALLER.bat`** — une seule fois, 5 à 15 minutes.
   Il crée l'environnement Python, installe Whisper, met **ffmpeg** en place et
   ajoute un raccourci sur le Bureau. Si Python manque, il t'indique exactement
   quoi faire.
2. Double-clique **`DEMARRER.bat`** (ou le raccourci du Bureau).

Deux ZIP sont proposés :

| Fichier | Taille | Quand le choisir |
|---|---|---|
| `DubPackCreator-Windows-v1.0.0-avec-ffmpeg.zip` | 72 Mo | **Recommandé.** ffmpeg est déjà dedans, rien à télécharger de plus. |
| `DubPackCreator-Windows-v1.0.0.zip` | 75 Ko | Si tu préfères un petit fichier : ffmpeg est téléchargé pendant l'installation. |

Sur macOS, voir « Lancement » plus bas.

## 1. Prérequis

| Outil | Rôle | Installation |
|---|---|---|
| **Python 3.10+** | fait tourner l'outil | [python.org/downloads](https://www.python.org/downloads/) — sous Windows, cocher **« Add Python to PATH »** |
| **ffmpeg** | découpe l'audio et encode la vidéo Theora | **Windows : automatique** (`INSTALLER.bat` s'en charge) · macOS : `brew install ffmpeg` |

> **ffmpeg doit contenir `libtheora`.** Le jeu tourne sous Godot, qui ne lit que
> l'Ogg Theora : sans cet encodeur, l'export de `dub_video.ogv` échoue.
> L'installeur Windows récupère la build *essentials* de gyan.dev, qui contient
> `libtheora` et `libvorbis`, et le vérifie. Sous macOS, la formule Homebrew les
> contient aussi. Le bandeau en haut de l'interface te le confirme
> (badge **Theora**).

> Sous macOS avec le Python de Homebrew, la boîte de dialogue « Choisir le
> dossier… » nécessite `brew install python-tk`. Sans elle, tu peux toujours
> coller le chemin à la main. Le Python officiel de Windows l'inclut déjà.

Le reste (Whisper, yt-dlp, serveur web) s'installe tout seul au premier
lancement, dans un environnement Python isolé (`.venv/`).

## 2. Lancement

**macOS** — double-clique `start.command`
*(au premier lancement : clic droit → Ouvrir, pour passer l'avertissement Gatekeeper).*

**Windows** — double-clique `start.bat`

**En ligne de commande** (les deux systèmes) :

```bash
python run.py
```

Le premier démarrage installe les dépendances (quelques minutes). Ensuite,
l'outil ouvre `http://127.0.0.1:8760` dans ton navigateur. Laisse la fenêtre
noire ouverte pendant l'utilisation ; `Ctrl+C` pour arrêter.

Options utiles :

```bash
python run.py --port 8888        # changer de port
python run.py --no-browser       # ne pas ouvrir le navigateur
python run.py --install-extras   # ajouter Demucs + empreintes vocales avancées
```

## 3. Comment ça marche

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

## 4. Où atterrit le pack (onglet Export)

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

**ZIP à télécharger** — l'archive classique, à installer à la main.

## 5. Installer le pack à la main

1. Décompresse le ZIP (ou prends directement le dossier exporté).
2. Copie le dossier du pack dans le dossier **`packs_voice`** du jeu.
   Les dub packs vont bien dans `packs_voice`, pas dans un dossier séparé.
3. Vérifie qu'il n'y a **pas de niveau de dossier en trop** :
   `packs_voice/Mon Pack/dub_video.ogv` doit exister — et non
   `packs_voice/Mon Pack/Mon Pack/dub_video.ogv`.
4. Lance le jeu et sélectionne le pack en mode Dub.

## 6. Ce qui est exporté

```
Mon Dub Pack/
├── _pack_info.ini                  titre, sous-titre, auteurs, icône
├── Icon.png                        vignette du pack
├── dub_video.ogv                   vidéo de référence (Theora + Vorbis)
├── _backing_track.ogg              fond sonore sans les voix (facultatif)
├── 01_lucie_marco-tu-as-vu.ogg     audio d'origine de la réplique
├── 01_lucie_marco-tu-as-vu.ini     métadonnées de la réplique
├── 02_marco_oui-lucie.ogg
├── 02_marco_oui-lucie.ini
└── README.txt                      rappel d'installation
```

Chaque réplique produit un `.ogg` (l'audio d'origine, que le joueur va imiter)
et un `.ini` de même nom, au format ConfigFile de Godot :

```ini
[data]

caption="Marco, tu as vu ce qui s'est passé hier soir ?"
dub_timestamps=[0.240]
dub_characters=["Lucie"]
```

- `caption` — le sous-titre affiché ;
- `dub_timestamps` — l'instant, en secondes, où la réplique se déclenche dans
  `dub_video.ogv` ;
- `dub_characters` — le personnage qui parle ; c'est ce qui permet au joueur de
  filtrer par personnage (les voix non choisies gardent l'audio d'origine) ;
- `images`, `tags`, `dub_only` — ajoutés seulement si tu les renseignes.

Les clips sont normalisés en volume par défaut : le scoring du jeu se comporte
mal sur les signaux trop faibles.

## 7. Fond sonore (musique et bruitages)

Pour que ta voix se pose sur la bande-son d'origine, le pack peut contenir un
`_backing_track.ogg`. Deux méthodes, dans l'onglet **Export** :

- **Séparer les voix (Demucs)** — isole musique et bruitages des dialogues.
  Nécessite Demucs et PyTorch (~2 Go) : `python run.py --install-extras`.
- **Utiliser l'audio d'origine** — reprend la bande-son complète, dialogues
  compris. Immédiat, mais on entend la voix d'origine sous la tienne.

## 8. Qualité de la détection des personnages

Le regroupement des voix repose sur des empreintes vocales (timbre + hauteur)
calculées localement, puis sur un regroupement hiérarchique. Le nombre de voix
est deviné automatiquement ; les répliques de moins d'une seconde sont classées
mais ne peuvent pas créer un personnage à elles seules.

Ça marche bien quand les voix sont nettement différentes. Pour des voix
proches, ou sur une source bruitée :

- fixe le **nombre de personnages** au lieu de laisser « auto », puis
  **Retranscrire** ;
- corrige les répliques restantes à la main (menu déroulant de chaque réplique) ;
- installe les empreintes vocales avancées (ECAPA-TDNN), plus précises :
  `python run.py --install-extras`.

Les noms sont devinés à partir des dialogues : un prénom prononcé en apostrophe
(« Marco, viens ! ») désigne presque toujours *l'autre* personnage, ce dont
l'outil tient compte. Vérifie toujours — c'est une heuristique, pas une
certitude.

## 9. Où sont mes fichiers

- `projects/<date>/` — un dossier par projet : vidéo source, audio de travail,
  `project.json` (tes modifications, sauvegardées automatiquement) ;
- `projects/<date>/export/` — le dossier du pack et son ZIP ;
- `.cache/models/` — les modèles Whisper téléchargés (supprimable) ;
- `.venv/` — l'environnement Python (supprimable ; il se recrée au lancement) ;
- `settings.json` — le dossier du jeu et la destination d'export mémorisés.

Supprimer un projet depuis l'accueil (🗑) efface tout son dossier.

## 10. Le panneau Diagnostic

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

## 11. En cas de problème

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
| Un lien vidéo échoue | `pip install -U yt-dlp` dans `.venv` : les sites changent souvent |
| Le port est déjà pris | l'outil en choisit un autre automatiquement — lis l'URL affichée dans la console |

## 12. Notes

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
