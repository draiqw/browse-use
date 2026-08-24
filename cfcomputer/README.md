# cfcomputer — песочница на Cloudflare Computer

Воркер поверх [`@cloudflare/computer`](https://github.com/cloudflare/computer) 0.2.1.
Даёт агенту рабочий каталог с файловой системой и шеллом. Поднимается локально
через `wrangler dev`, аккаунт Cloudflare не нужен.

## Что внутри

Durable Object `Box` держит воркспейс: файловая система лежит в SQLite самого
объекта, а шелл (`just-bash`) крутится в Dynamic Worker, который поднимается
через биндинг `LOADER`. Каждый `exec` ходит за файлами обратно в тот же DO,
поэтому второго хранилища и синхронизации нет.

Разные имена в URL — разные воркспейсы, файлы друг друга они не видят.

## Запуск

```sh
npm install
npx wrangler types     # генерирует worker-configuration.d.ts, в git не хранится (572 КБ)
npm run dev            # http://127.0.0.1:8788
```

## HTTP-контракт

```
POST   /box/<id>/exec                    {"command": "...", "cwd": "/workspace"}
PUT    /box/<id>/file/workspace/<путь>   тело — содержимое файла
GET    /box/<id>/file/workspace/<путь>
GET    /box/<id>/tree                    плоский список файлов
DELETE /box/<id>                         вычистить /workspace
GET    /health
```

Пример:

```sh
curl -s -X POST localhost:8788/box/demo/exec \
  -H 'content-type: application/json' \
  -d '{"command":"echo hi > a.txt; wc -c a.txt"}'
```

Контракт нарочно плоский: его дёргает питонья часть (`sandbox/box.py`), и через
неё — любая модель, а не только те, у кого есть готовый SDK под AI SDK.

## Что доступно внутри песочницы

Ядро `just-bash`: `cat ls grep sed awk sort uniq head tail wc tr cut find xargs
echo printf test date base64 md5sum sha256sum tar gzip`, плюс `git` и `jq`.

Чего нет:

- **сети.** У Dynamic Worker `globalOutbound` закрыт, а группу команд `curl`
  мы не подключаем. Для задач это удобно: агент не может подсмотреть ответ снаружи.
- **`python` и `node`.** Интерпретаторов в ядре нет.
- **групп `python` и `sqlite` из пакета.** В 0.2.1 они в воркере не поднимаются:
  `python3` отвечает `command not available in browser environments`, а
  `sqlite3` — `sqlite3 worker not found. Run 'pnpm build'`. Проверено на
  опубликованном npm-пакете, не на исходниках репозитория. Поэтому они не
  импортируются — иначе агент тратил бы шаги на инструмент, которого нет.
- **контейнерного бэкенда.** Полный Linux в `@cloudflare/computer` есть, но он
  требует Cloudflare Containers, то есть аккаунта и деплоя. Здесь только
  worker-shell, который работает локально.

## Оговорка апстрима

Пакет помечен как **PREVIEW ONLY**: API нестабилен, для продакшена не годится.
Версия закреплена точно (`0.2.1`, без `^`), чтобы обновление не поменяло
поведение под ногами.
