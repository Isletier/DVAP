#!/bin/bash
# При выходе убить все дочерние процессы
trap "kill 0" EXIT

# 1. Стартуем сервер
nohup dlv debug --headless --listen=:2345 --api-version=2 --accept-multiclient --check-go-version=false &

# 2. Ждем, пока порт откроется
while ! nc -z localhost 2345; do sleep 0.1; done

# 3. Стартуем ваш скрапер
#./my_scraper --target=:2345 &

# 4. Входим в интерактивный режим
dlv connect :2345

