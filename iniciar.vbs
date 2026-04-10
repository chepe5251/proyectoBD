On Error Resume Next

Dim carpeta, oShell, oFSO, retCode

carpeta = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))

Set oFSO   = CreateObject("Scripting.FileSystemObject")
Set oShell = CreateObject("WScript.Shell")

' 1. Verificar que existe main.py
If Not oFSO.FileExists(carpeta & "main.py") Then
    MsgBox "No se encontro main.py. Asegurate de ejecutar este archivo desde la carpeta del proyecto.", _
           vbCritical, "Error de configuracion"
    WScript.Quit
End If

' 2. Verificar que existe .env
If Not oFSO.FileExists(carpeta & ".env") Then
    MsgBox "No se encontro el archivo .env con las credenciales del sistema. " & _
           "Crea el archivo .env en esta carpeta antes de continuar.", _
           vbExclamation, "Configuracion requerida"
    WScript.Quit
End If

' 3. Verificar que Python esta instalado
retCode = oShell.Run("cmd /c python --version > nul 2>&1", 0, True)
If retCode <> 0 Then
    MsgBox "Python no esta instalado o no esta en el PATH del sistema. " & _
           "Instala Python 3.10 o superior desde python.org.", _
           vbCritical, "Python no encontrado"
    WScript.Quit
End If

' 4. Establecer directorio de trabajo y lanzar la app sin consola
oShell.CurrentDirectory = carpeta
oShell.Run "pythonw main.py", 0, False

' 5. Manejo de error inesperado
If Err.Number <> 0 Then
    MsgBox "Ocurrio un error al iniciar la aplicacion: " & Err.Description, _
           vbCritical, "Error inesperado"
End If
