import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { MotionConfig } from 'motion/react'
import App from './App'
import { AuthProvider } from './auth'
import { ToastProvider, applyTheme, initialTheme } from './ui'
import './index.css'

applyTheme(initialTheme())

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      {/* Animations follow the OS "reduce motion" setting */}
      <MotionConfig reducedMotion="user">
        <AuthProvider><ToastProvider><App /></ToastProvider></AuthProvider>
      </MotionConfig>
    </BrowserRouter>
  </StrictMode>,
)
