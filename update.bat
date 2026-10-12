@echo off
rem Capture every dynasty screen from chiaki-ng, extract the data and publish the site.
rem Open chiaki-ng on the Dynasty hub first, then double-click this file.
cd /d "%~dp0"
python tools\publish.py --capture
echo.
pause
