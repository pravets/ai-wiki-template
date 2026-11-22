---
name:
type: repo
created:
updated:
tags: []
repo: owner/name
role: maintainer | contributor | watcher | archived
status: active | on-demand | paused | archived | unknown
upstream: ""        # owner/name, только для форков с собственными коммитами
local_path: ""      # ~/project, если клон есть на машине
stack: []
sources:
  - https://github.com/owner/name
---
## Что это

Одна-две фразы: зачем проект существует и для кого. Не пересказ README — смысл.

## Моя роль

Что именно делаю: мейнтейню и решаю по PR, шлю изменения к чужому мейнтейнеру, слежу за upstream. Что здесь моё, а что чужое.

## Журнал

События — append-only в `42-repos/log.md`, строками `## [YYYY-MM-DD] owner/name | суть`.
Здесь — только устойчивое: зачем репозиторий в базе.

## Ссылки

- Репозиторий: https://github.com/owner/name
