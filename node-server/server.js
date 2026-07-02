const express = require('express');
const path = require('path');
const { createProxyMiddleware } = require('http-proxy-middleware');

const app = express();
const PORT = process.env.PORT || 3000;
const BACKEND_URL = process.env.BACKEND_URL || 'http://backend:8000';

// Все запросы /api/* уходят на Python-бэкенд (FastAPI).
// ВАЖНО: при app.use('/api', ...) Express сам обрезает префикс /api из req.url
// до того, как он попадёт в прокси-мидлвар, поэтому без pathRewrite бэкенд
// получит "/telegram/..." вместо "/api/telegram/..." и ответит 404 — возвращаем
// префикс обратно явно.
app.use(
  '/api',
  createProxyMiddleware({
    target: BACKEND_URL,
    changeOrigin: true,
    pathRewrite: (path) => '/api' + path,
  })
);

// Статика фронтенда (чистый HTML/CSS/jQuery, без сборщиков)
app.use(express.static(path.join(__dirname, 'frontend')));

// Любой остальной маршрут отдаёт index.html (для простоты SPA-подобной навигации)
app.get('*', (req, res) => {
  res.sendFile(path.join(__dirname, 'frontend', 'index.html'));
});

app.listen(PORT, () => {
  console.log(`Node server запущен на порту ${PORT}, проксирование /api -> ${BACKEND_URL}`);
});
