@echo off
REM Check if two arguments (input file and output file) are provided
if "%~1"=="" (
    echo Please provide the input XML file path.
    exit /b 1
)

if "%~2"=="" (
    echo Please provide the output file path.
    exit /b 1
)

REM Assign arguments to variables
set "inputFile=%~1"
set "outputFile=%~2"

REM Check if the input file exists
if not exist "%inputFile%" (
    echo Input file "%inputFile%" does not exist.
    exit /b 1
)

REM Execute PowerShell command to extract 'id' attributes and write to output file without BOM
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$xml = [xml](Get-Content '%inputFile%');" ^
    "$ids = $xml.SelectNodes('//attribute[@id]').id;" ^
    "$ids -join ',' | Set-Content '%outputFile%' -Encoding ASCII"

REM Confirm completion
echo ID values extracted and written to "%outputFile%"
