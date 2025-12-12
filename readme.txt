Инструкция по использованию generate_links.py

Назначение
Скрипт читает список адресов из текстового файла и формирует для каждого адреса ссылку на Яндекс.Карты, которая на iPhone открывает приложение и сразу переводит в режим построения маршрута на общественном транспорте до точки назначения.

Формат ссылок
https://yandex.ru/maps/?mode=routes&rtext=~<lat>,<lon>&rtt=masstransit
— пустое начало в rtext означает «от текущего местоположения».
— rtt=masstransit — маршрут на общественном транспорте.

Требования
— Python 3.8+ (подойдет 3.13)
— Доступ в интернет для геокодирования (по умолчанию — Яндекс Геокодер)
— Заполненный файл yandex_api_key.py (значение YANDEX_GEOCODER_API_KEY)
— (опционально) пакет certifi для более полной базы корневых сертификатов

Входные данные
— Файл addresses.txt: по одному адресу на строку. Пример:
  Тверской бульвар, 20с4
  улица Большая Полянка, 30
— Комментарии: строки, начинающиеся с #, игнорируются.
— Можно явно указать координаты для адреса в формате:
  Адрес | 55.7609149,37.6031833
  В этом случае геокодирование не выполняется, берутся заданные координаты.

Выходные форматы
1) CSV (по умолчанию): столбцы Address,YandexMapsLink, файл links.csv.
2) Пары (pairs): строки вида «Адрес/URL», между парами пустая строка для удобного чтения, файл links.txt.

Подготовка
— Откройте файл yandex_api_key.py и впишите значение вашего ключа в строку YANDEX_GEOCODER_API_KEY = "".

Быстрый старт
— Сгенерировать CSV:
  - Windows (cmd/PowerShell): python generate_links.py -o links.csv
  - macOS/Linux (bash/zsh):   python3 generate_links.py -o links.csv

— Сгенерировать пары (с пустой строкой между ними):
  - Windows: python generate_links.py --format pairs -o links.txt
  - macOS/Linux: python3 generate_links.py --format pairs -o links.txt

Повышение точности геокодирования
— Добавьте контекст города/региона (рекомендуется для Москвы):
  python3 generate_links.py --prepend "Москва, " --format pairs -o links.txt

Геокодер и ключи
— По умолчанию используется Яндекс Геокодер. Ключ подтягивается из yandex_api_key.py.
— Можно указать альтернативный ключ параметром --apikey (если хотите временно переопределить значение из файла).
— Доступны альтернативные сервисы:
  - Nominatim (OpenStreetMap):
      Windows: python generate_links.py --geocoder nominatim ...
      macOS/Linux: python3 generate_links.py --geocoder nominatim ...
  - Photon (OpenStreetMap/Komoot):
      Windows: python generate_links.py --geocoder photon ...
      macOS/Linux: python3 generate_links.py --geocoder photon ...
— Для корректного использования Nominatim можно (необязательно) указать email (переменная NOMINATIM_EMAIL).

Выбор домена Яндекс.Карт
— По умолчанию: yandex.ru. Можно переключиться на yandex.com:
  - Windows: python generate_links.py --domain yandex.com -o links.csv
  - macOS/Linux: python3 generate_links.py --domain yandex.com -o links.csv

Кэширование
— Результаты геокодирования сохраняются в geocache.json.
— Чтобы пересчитать координаты, удалите этот файл и запустите скрипт снова.

Поведение при ошибках геокодирования
— Скрипт сначала пробует выбранный геокодер, затем автоматически резервные сервисы (Photon, затем Nominatim/Яндекс) и возвращает первую найденную пару координат.
— Если все сервисы вернули пустой ответ, линк собирается по тексту адреса.
— В редких случаях такой URL может не построить маршрут. В этом случае:
  1) Уточните адрес (добавьте корпус/строение),
  2) Используйте --prepend "Москва, ",
  3) Либо укажите координаты в исходном файле как «Адрес | lat,lon».
— При смене логики геокодирования или уточнении адресов удалите geocache.json, чтобы пересчитать координаты.

Примеры
— CSV для адресов по Москве:
  - Windows: python generate_links.py --prepend "Москва, " -o links.csv
  - macOS/Linux: python3 generate_links.py --prepend "Москва, " -o links.csv

— Пары с координатами через Nominatim:
  - Windows: python generate_links.py --geocoder nominatim --format pairs -o links.txt
  - macOS/Linux: python3 generate_links.py --geocoder nominatim --format pairs -o links.txt

— Пары с Photon:
  - Windows: python generate_links.py --geocoder photon --format pairs -o links.txt
  - macOS/Linux: python3 generate_links.py --geocoder photon --format pairs -o links.txt

Структура репозитория
— addresses.txt  — входной список адресов
— generate_links.py — скрипт генерации ссылок
— links.csv / links.txt — результаты в выбранном формате
— geocache.json — кэш геокодирования

Примечание
— На iPhone ссылки вида https://yandex.ru/maps/... открывают приложение Яндекс.Карт (при установленном приложении) благодаря Universal Links и сразу запускают построение маршрута в нужном режиме.
— Скрипт автоматически переключается между Nominatim, Photon и (при наличии ключа) Яндекс Геокодером, чтобы вернуть координаты даже для сложных адресов и корпусов.
