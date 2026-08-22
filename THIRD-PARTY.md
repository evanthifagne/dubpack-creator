# Composants tiers et indépendance du projet

## Indépendance

Ce projet est **indépendant**. Il n'est affilié ni au jeu *The Choicer Voicer*
ni à ses auteurs, et ne reprend aucun code d'un autre outil de création de
packs. Le format de pack implémenté suit la documentation publique du jeu.

## Composants utilisés à l'exécution

Ils sont installés par `INSTALLER.bat` (ou `pip install -r requirements.txt`) et
conservent leurs propres licences :

| Composant | Rôle | Licence |
|---|---|---|
| [FFmpeg](https://ffmpeg.org/) | découpe audio, encodage Theora/Vorbis | LGPL 2.1+ / GPL selon la build |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | transcription (Whisper via CTranslate2) | MIT |
| [Whisper](https://github.com/openai/whisper) (modèles) | modèles de transcription | MIT |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | récupération des vidéos par lien | Unlicense |
| [FastAPI](https://fastapi.tiangolo.com/) / [Uvicorn](https://www.uvicorn.org/) | serveur local | MIT / BSD-3 |
| [NumPy](https://numpy.org/) / [SciPy](https://scipy.org/) | empreintes vocales et regroupement | BSD-3 |
| [Demucs](https://github.com/adefossez/demucs) *(optionnel)* | séparation voix / fond sonore | MIT |
| [SpeechBrain](https://speechbrain.github.io/) *(optionnel)* | empreintes vocales ECAPA-TDNN | Apache 2.0 |

La build Windows de FFmpeg installée automatiquement provient de
[gyan.dev](https://www.gyan.dev/ffmpeg/builds/), la source recommandée par le
projet FFmpeg. Sous macOS, le binaire FFmpeg est celui de la roue Python
[imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) (BSD-2, binaire
FFmpeg sous LGPL/GPL).

## Composants embarqués par l'installeur et l'application

| Composant | Rôle | Licence |
|---|---|---|
| [CPython](https://www.python.org/) via [python-build-standalone](https://github.com/astral-sh/python-build-standalone) | interpréteur Python embarqué | PSF-2.0 |
| Lanceur natif écrit en [Go](https://go.dev/) | démarrage, supervision, mises à jour | code du projet (MIT) ; runtime Go BSD-3 |
| [Tabler Icons](https://tabler.io/icons) | icônes de l'interface | MIT |

L'installeur Windows est construit avec [NSIS](https://nsis.sourceforge.io/)
(licence zlib).

## Contenu que tu produis

Respecte les droits des vidéos que tu utilises et les règles de la communauté du
jeu. Cet outil ne fournit aucun contenu : il transforme celui que tu lui donnes.
