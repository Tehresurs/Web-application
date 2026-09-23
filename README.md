# Excel AI Agent

Веб-приложение для автоматизации обработки Excel-файлов.

## Архитектура

- Frontend — Next.js
- Backend — FastAPI
- AI — OpenAI
- Database — PostgreSQL
- Memory — PostgreSQL + pgvector
- Excel — pandas + openpyxl

## Запуск

### Backend

```bash
cd backend
.venv\Scripts\Activate.ps1
uvicorn main:app --reload
```

Страница обработки доступна по адресу `http://127.0.0.1:8000/`.
Кнопка «Запустить проверку» вызывает `POST /api/process-folder` с JSON
`{"path": "C:\\Путь\\к\\отчётам"}`. Путь относится к файловой системе сервера.
Ответ содержит `total`, `ok`, `warning`, `error` и массив `reports`, который
используют счётчики, таблица, фильтры и панель просмотра. Отчёты сортируются по ФИО.
Ошибки чтения файлов возвращаются отдельно в `processing_errors` и отображаются
в таблице со статусом ошибки; временные файлы Word `~$` пропускаются.
API не создаёт HTML-файлы. Диагностические HTML-отчёты по-прежнему можно получить
отдельным запуском `python -m app.parsers.word_parser` из папки `backend`.

Проверки обработки: `python -m unittest discover -s tests -v` из папки `backend`.

### Frontend

```bash
cd frontend
npm run dev
```
