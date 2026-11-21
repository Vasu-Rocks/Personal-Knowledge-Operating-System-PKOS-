; PKOS additions to the electron-builder NSIS installer.

; Stops PKOS's own background processes (database, Ollama, engine) still running from the install folder, so files
; can be replaced or removed. Matches by executable path, so other PostgreSQL/Ollama installs are never touched.
!macro pkosStopChildren
  nsExec::Exec `powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "Get-Process | Where-Object { $$_.Path -and $$_.Path.StartsWith('$INSTDIR\', 'OrdinalIgnoreCase') } | Stop-Process -Force -ErrorAction SilentlyContinue"`
  Pop $0
!macroend

!macro customInit
  !insertmacro pkosStopChildren
!macroend

!macro customUnInit
  !insertmacro pkosStopChildren
!macroend

; Uninstall keeps the vault unless the user explicitly asks to delete it. Updates (which uninstall the old version
; silently) never delete data.
!macro customUnInstall
  ${ifNot} ${isUpdated}
    MessageBox MB_YESNO|MB_ICONQUESTION|MB_DEFBUTTON2 \
      "Also delete your PKOS data?$\r$\n$\r$\nThis removes your documents, database and downloaded AI models in$\r$\n$LOCALAPPDATA\PKOS$\r$\n$\r$\nChoose No to keep them for a later reinstall." \
      /SD IDNO IDNO pkos_keep_data
      RMDir /r "$LOCALAPPDATA\PKOS"
    pkos_keep_data:
  ${endIf}
!macroend
