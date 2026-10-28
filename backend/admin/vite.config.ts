import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 開発中（npm run dev）は、API をバックエンド（管理画面ポート 8080）へ流す。
// 本番は、ビルドした画面を Go が配るので、同じ入口になる。
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": { target: "http://localhost:8080", ws: true },
    },
  },
  build: { outDir: "dist", emptyOutDir: true },
});
