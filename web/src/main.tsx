import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import { apply, loadPref, resolve } from './lib/theme'
// Bundled, so the UI is set the same everywhere, offline included.
import '@fontsource-variable/inter'
import '@fontsource-variable/jetbrains-mono'
import './styles.css'

// Before the first render, so the page never flashes the wrong theme.
apply(resolve(loadPref()))

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
