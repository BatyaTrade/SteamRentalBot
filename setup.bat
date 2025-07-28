@echo off
setlocal

echo [SETUP] Проверка Docker...
docker --version >nul 2>&1
if %errorlevel% == 0 (
    echo [SETUP] Docker найден.
) else (
    echo [SETUP] ОШИБКА: Docker не найден.
    echo        Установите Docker Desktop: https://docs.docker.com/desktop/install/windows-install/
    pause
    exit /b 1
)

echo [SETUP] Проверка docker-compose...
docker-compose --version >nul 2>&1
if %errorlevel% == 0 (
    echo [SETUP] docker-compose найден.
) else (
    echo [SETUP] ОШИБКА: docker-compose не найден. Обычно входит в Docker Desktop.
    pause
    exit /b 1
)

echo [SETUP] Проверка .env файла...
if not exist ".env" (
    echo [SETUP] Создание .env из .env.example...
    copy ".env.example" ".env" >nul
    if %errorlevel% == 0 (
        echo [SETUP] Файл .env создан.
        echo [SETUP] Пожалуйста, отредактируйте .env в текстовом редакторе и введите свои данные.
        echo [SETUP] После этого выполните 'docker-compose up --build'
    ) else (
        echo [SETUP] ОШИБКА: Не удалось создать .env.
        pause
        exit /b 1
    )
) else (
    echo [SETUP] Файл .env уже существует. Убедитесь, что он заполнен.

)

echo.
echo [SETUP] Готово!
echo [SETUP] Следующий шаг: Откройте .env и заполните его. Затем выполните:
echo           docker-compose up --build
echo.
pause