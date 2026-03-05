@echo off
taskkill /FI "WINDOWTITLE eq paper" /T /F
taskkill /FI "WINDOWTITLE eq live" /T /F
taskkill /FI "WINDOWTITLE eq research" /T /F
taskkill /FI "WINDOWTITLE eq status" /T /F
taskkill /FI "WINDOWTITLE eq self_check" /T /F
