# Банк прецедентных текстов — хаб

Выборки строятся Dataview из frontmatter карточек `15-precedent/bank/`. Руками таблицы не править — обновляются сами. Контракт зоны — [[15-precedent/README]], словарь тем и приёмов — [[15-precedent/themes]].

## Весь банк

```dataview
TABLE WITHOUT ID file.link AS "Карточка", author AS "Автор", work AS "Источник", year AS "Год", theme AS "Темы", device AS "Приём", attribution AS "Атрибуция"
FROM "15-precedent/bank"
SORT author ASC, year ASC
```

## По темам

```dataview
TABLE WITHOUT ID key AS "Тема", length(rows) AS "Цитат", rows.file.link AS "Карточки"
FROM "15-precedent/bank"
FLATTEN theme
GROUP BY theme AS key
SORT length(rows) DESC
```

## По приёмам в докладе

```dataview
TABLE WITHOUT ID key AS "Приём", length(rows) AS "Цитат", rows.file.link AS "Карточки"
FROM "15-precedent/bank"
FLATTEN device
GROUP BY device AS key
SORT length(rows) DESC
```

## Требуют проверки

`attribution` не `primary`: либо не сверено с первоисточником, либо атрибуция ложная.

```dataview
TABLE WITHOUT ID file.link AS "Карточка", author AS "Автор", attribution AS "Атрибуция", sources AS "Источники"
FROM "15-precedent/bank"
WHERE attribution != "primary"
SORT attribution ASC, author ASC
```

## Где уже использовано

```dataview
TABLE WITHOUT ID file.link AS "Карточка", author AS "Автор", used_in AS "Материалы"
FROM "15-precedent/bank"
WHERE length(used_in) > 0
SORT author ASC
```

## Ещё не использовано

```dataview
LIST author + " — " + work
FROM "15-precedent/bank"
WHERE length(used_in) = 0
SORT author ASC
```
