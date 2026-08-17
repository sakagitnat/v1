import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Cloudflare Pages: build output goes to /dist, serve as static site.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist",
  },
});
