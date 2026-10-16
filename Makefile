.PHONY: install sync test run docker clean

install sync:
	uv sync

test:
	uv run pytest

run:
	uv run polymarket/server.py

docker:
	docker compose up --watch

clean:
	rm -rf .venv .pytest_cache __pycache__ polymarket/**/__pycache__
	rm -f *.db *.db-journal *.db-shm *.db-wal
