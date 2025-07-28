# Makefile
.PHONY: check-docker check-env setup build run stop clean

check-docker:
    @which docker > /dev/null || (echo "Docker не установлен. Установите его с https://docs.docker.com/get-docker/" && exit 1)
    @which docker-compose > /dev/null || (echo "docker-compose не установлен." && exit 1)
    @echo "Docker и docker-compose найдены."

check-env:
    @if [ ! -f .env ]; then \
        echo "Файл .env не найден. Создаю из .env.example..."; \
        cp .env.example .env; \
        echo "Пожалуйста, отредактируйте .env и заполните переменные!"; \
    else \
        echo ".env файл найден."; \
    fi

setup: check-docker check-env
    @echo "Проверка завершена. Готов к сборке."

build: setup
    docker-compose build

run: build
    docker-compose up

stop:
    docker-compose down

clean:
    docker-compose down -v --remove-orphans