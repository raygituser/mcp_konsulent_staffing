.PHONY: up down logs ps build test lint format up-local-gguf up-obs up-redis up-edge

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f --tail=200

ps:
	docker compose ps

build:
	docker compose build

up-local-gguf:
	docker compose --profile local-gguf up --build

up-obs:
	docker compose --profile observability up -d --build

up-redis:
	docker compose --profile redis up -d --build

up-edge:
	docker compose --profile edge up -d --build

test:
	pytest -q

lint:
	ruff check .

format:
	ruff format .
