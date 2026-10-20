# VectorNaso

Applicazione locale per convertire immagini raster in grafica vettoriale. Le immagini vengono elaborate sul computer.

Il codice e gli asset dell'applicazione sono pubblicati per creare i pacchetti macOS. La cartella `Samples` è inclusa nel DMG.

## DMG macOS

Apri la scheda **Actions** del repository GitHub e avvia **Build macOS DMGs**. La compilazione crea due pacchetti: Apple Silicon (`arm64`) e Mac Intel (`x86_64`). Scarica l'artefatto corrispondente al tuo Mac dalla conclusione dell'esecuzione.

Per generare localmente il pacchetto, usa `packaging/Build-macOS.command` su macOS. La prima esecuzione installa le dipendenze Python indicate in `requirements.txt`.
