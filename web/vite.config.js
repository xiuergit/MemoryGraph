import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

function readDeskPort() {
  const portFile = path.resolve(__dirname, '../data/.memory_desk_port')
  try {
    const text = fs.readFileSync(portFile, 'utf8').trim()
    if (/^\d+$/.test(text)) {
      return text
    }
  } catch {
    // fall through
  }
  return process.env.MEMORY_DESK_PORT || process.env.VITE_DESK_PORT || '8766'
}

const deskPort = readDeskPort()
const deskTarget = `http://127.0.0.1:${deskPort}`

console.log(`[vite] API proxy → ${deskTarget}`)

export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      '/api': {
        target: deskTarget,
        changeOrigin: true,
      },
      '/photos': {
        target: deskTarget,
        changeOrigin: true,
      },
    },
  },
})
