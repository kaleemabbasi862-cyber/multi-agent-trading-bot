# TradeTalk V2 — Deployment & Operation Guide

## 1. Local Run
```bash
# Install dependencies
pip install -r requirements.txt

# Run automated tests
python run_tests.py

# Start local server
python main_native.py
```
Server runs at `http://localhost:8000`.

---

## 2. Render Cloud Deployment
1. Push code to GitHub repository (`main` branch).
2. Render automatically builds with `pip install -r requirements.txt` and executes:
   ```bash
   uvicorn main_native:app --host 0.0.0.0 --port $PORT
   ```
3. Verify `/health` endpoint returns `{"status": "healthy"}`.
