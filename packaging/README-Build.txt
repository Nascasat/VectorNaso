VectorNaso — pacchetti Windows e macOS

WINDOWS
Eseguire PowerShell dalla cartella packaging:
  .\Build-Windows.ps1

Il risultato è VectorNaso-Setup.exe, un installer per l'utente corrente, e VectorNaso-Windows.zip, una versione portatile. Entrambi includono la cartella Samples; l'app include Python e le dipendenze e non richiede Python installato per l'uso. Per creare il pacchetto è richiesta una connessione al primo build. L'eseguibile non è firmato: Windows può mostrare il relativo avviso SmartScreen.

macOS
La build macOS deve essere eseguita su un Mac con Xcode Command Line Tools e Python 3 installati:
  chmod +x packaging/Build-macOS.command
  ./packaging/Build-macOS.command

Genera un DMG da trascinare in Applicazioni e uno ZIP dell'app. Il DMG include anche Samples. macOS potrebbe mostrare l'avviso Gatekeeper perché il pacchetto non è firmato né notarizzato.

Il sorgente Python dell'app usa la cartella di risorse PyInstaller quando è congelato. I dati web e Samples vengono inclusi nella build.
