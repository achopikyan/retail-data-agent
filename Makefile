.PHONY: help install seed run test eval curate replay api web dc-up dc-down clean

help:
	@echo "Targets:"
	@echo "  install   — pip install -r requirements.txt"
	@echo "  seed      — embed Golden Bucket Trios (one-time)"
	@echo "  run       — start the interactive CLI"
	@echo "  api       — start the FastAPI server (uvicorn :8000)"
	@echo "  web       — start the React dev server (vite :5173)"
	@echo "  dc-up     — docker compose up --build (api + web)"
	@echo "  dc-down   — docker compose down"
	@echo "  test      — run the offline test suite"
	@echo "  eval      — run the (live) golden eval against BigQuery"
	@echo "  curate    — promote 👍-voted Trios into the Golden Bucket"
	@echo "  replay    — pretty-print the latest session log"
	@echo "  clean     — remove caches, embeddings, and session logs"

install:
	pip install -r requirements.txt

seed:
	python -m scripts.seed_golden_bucket

run:
	python -m src.cli

test:
	pytest tests/ -v

eval:
	python -m scripts.run_eval

curate:
	python -m scripts.curate

replay:
	python -m scripts.replay --latest

api:
	uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000

web:
	cd web && npm install && npm run dev

dc-up:
	docker compose up --build

dc-down:
	docker compose down

clean:
	rm -rf __pycache__ .pytest_cache **/__pycache__
	rm -f data/golden_trios.embeddings.npy
	rm -f data/curated_trios.json
	rm -f data/app.db
	rm -f logs/session_*.jsonl
