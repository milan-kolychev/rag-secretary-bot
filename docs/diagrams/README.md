# Диаграммы (пп. 4, 7, 9, 10, 11 чек-листа)

Исходники PlantUML (`*.puml`) и готовые PNG. Общие настройки (ч/б, Times-совместимый
шрифт): `_style.iuml`. Код можно вставить в SmartDraw или любой редактор PlantUML.

| Файл | Пункт | Содержание |
|---|---|---|
| `04_use_cases` | 4 | UC-диаграмма |
| `07_activity_autoanswer` | 7 | Деятельность «Автоответ» |
| `07_activity_escalation_1_handover` | 7 | «Эскалация»: передача вопроса |
| `07_activity_escalation_2_reply` | 7 | «Эскалация»: ответ секретаря |
| `09_classes_overview`, `09_classes_bot`, `09_classes_api` | 9 | Диаграммы классов |
| `10_mockup_student`, `10_mockup_secretary`, `10_storyboard` | 10 | Макет и раскадровка |
| `11_transitions_student`, `11_transitions_secretary` | 11 | Схема переходов |

Пересборка PNG (нужны Java и Graphviz):

```bash
java -jar plantuml.jar -tpng docs/diagrams/*.puml
uv run --with playwright python docs/diagrams/mockups/build_mockups.py
```
