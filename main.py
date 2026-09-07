"""
TradeTalk AI - Main Application Gateway
Forwards entrypoint to main_native.py for full compatibility across all deployment environments (Render, local, Docker).
"""
import os
import sys
import uvicorn
from main_native import app

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)

