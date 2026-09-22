import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// Das gebaute Frontend wird vom Bot-aiohttp-Server unter "/" ausgeliefert.
// WICHTIG: Build-Assets liegen unter /appassets/ — NICHT /assets/, denn /assets/
// ist im Bot bereits für das Logo (webassets/) belegt.
export default defineConfig({
  plugins: [react()],
  base: "/",
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  build: {
    outDir: "dist",
    assetsDir: "appassets",
    emptyOutDir: true,
    rollupOptions: {
      output: {
        // Vendor-Code in stabile Chunks aufteilen: motion (groß, nicht überall
        // gebraucht) separat, der Rest in einen vendor-Chunk. Diese ändern sich
        // selten → bessere Browser-Cache-Trefferquote zwischen Deploys.
        manualChunks(id) {
          if (id.includes("node_modules")) {
            if (id.includes("/motion") || id.includes("framer-motion"))
              return "motion";
            return "vendor";
          }
        },
      },
    },
  },
  server: {
    port: 5173,
    // Dev-Komfort: API & Assets an dev_panel.py weiterreichen (Port 8099, Dummy-Login
    // + echte DB). So bekommt man `npm run dev` mit Live-Reload UND echten Daten.
    proxy: {
      "/api": { target: "http://127.0.0.1:8099", changeOrigin: true },
      "/login": { target: "http://127.0.0.1:8099", changeOrigin: true },
      "/callback": { target: "http://127.0.0.1:8099", changeOrigin: true },
      "/logout": { target: "http://127.0.0.1:8099", changeOrigin: true },
      "/static": { target: "http://127.0.0.1:8099", changeOrigin: true },
      "/assets": { target: "http://127.0.0.1:8099", changeOrigin: true },
    },
  },
});
