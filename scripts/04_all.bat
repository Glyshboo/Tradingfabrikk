@echo off
start "paper" cmd /c python -m apps.paper_runner --config configs/active.yaml
start "research" cmd /c python -m apps.research_runner --config configs/active.yaml --space configs/research_space.yaml
