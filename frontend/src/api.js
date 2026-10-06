import axios from 'axios'

// Shared axios instance: the Vite dev server proxies /api to the FastAPI backend.
export const api = axios.create({
  baseURL: '/api',
  timeout: 120000,
})

export default api
