@echo off
setlocal

set "WINAI_LLM_URL=http://localhost:11434"
set "WINAI_LLM_MODEL=qwen2.5:7b"

c:/Users/sondh/winai/.venv/Scripts/python.exe main.py --llm-url "%WINAI_LLM_URL%" --llm-model "%WINAI_LLM_MODEL%"

endlocal
