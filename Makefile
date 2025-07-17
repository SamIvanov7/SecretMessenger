.PHONY: help build up down restart logs shell test clean

help:
	@echo "Available commands:"
	@echo "  make build    - Build Docker images"
	@echo "  make up       - Start all services"
	@echo "  make down     - Stop all services"
	@echo "  make restart  - Restart all services"
	@echo "  make logs     - View logs"
	@echo "  make shell    - Enter backend shell"
	@echo "  make test     - Run tests"
	@echo "  make clean    - Clean up containers and volumes"

build:
	docker-compose build

up:
	docker-compose up -d

down:
	docker-compose down

restart:
	docker-compose restart

logs:
	docker-compose logs -f

shell:
	docker-compose exec backend bash

test:
	docker-compose exec backend pytest

clean:
	docker-compose down -v
	rm -rf backend/__pycache__
	rm -rf backend/.pytest_cache
	rm -rf backend/uploads/*

migrate:
	docker-compose exec backend alembic upgrade head

migration:
	docker-compose exec backend alembic revision --autogenerate -m "$(message)"