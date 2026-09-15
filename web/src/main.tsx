import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import './styles.css'

const saved = localStorage.getItem('selfcheck.theme')
if (saved === 'light' || saved === 'dark') {
  document.documentElement.dataset.theme = saved
} else if (window.matchMedia('(prefers-color-scheme: light)').matches) {
  document.documentElement.dataset.theme = 'light'
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
