import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Адреса backend API для dev-сервера. У Docker — http://api:8000 (ім'я сервісу),
// без Docker — http://localhost:8000. Це налаштування Node-сервера Vite,
// у браузер воно не потрапляє.
const apiUrl = process.env.API_URL || "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    strictPort: true,
    // На Windows/WSL 2 події зміни файлів не доходять у контейнер — перевіряємо опитуванням
    watch: { usePolling: true },
    // Браузер звертається до /api/... на тому ж адресі, що й сторінка,
    // а Vite пересилає запит на backend. Тому React не знає адреси бази й секретів.
    proxy: {
      "/api": { target: apiUrl, changeOrigin: true },
    },
  },
});
