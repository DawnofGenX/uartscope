import { useState, useEffect } from 'react'
import './InstallPrompt.css'

interface BeforeInstallPromptEvent extends Event {
  prompt(): Promise<void>
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>
}

let deferredPrompt: BeforeInstallPromptEvent | null = null

export function useInstallPrompt() {
  const [installable, setInstallable] = useState(false)
  const [installed, setInstalled] = useState(false)

  useEffect(() => {
    // Check if already installed
    if (window.matchMedia('(display-mode: standalone)').matches) {
      setInstalled(true)
      return
    }

    const handler = (e: Event) => {
      e.preventDefault()
      deferredPrompt = e as BeforeInstallPromptEvent
      setInstallable(true)
    }

    window.addEventListener('beforeinstallprompt', handler)

    // For iOS Safari (no beforeinstallprompt)
    const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent)
    const isSafari = /^((?!chrome|android).)*safari/i.test(navigator.userAgent)
    if (isIOS && isSafari && !window.matchMedia('(display-mode: standalone)').matches) {
      setInstallable(true)
    }

    return () => window.removeEventListener('beforeinstallprompt', handler)
  }, [])

  const install = async () => {
    if (deferredPrompt) {
      await deferredPrompt.prompt()
      const { outcome } = await deferredPrompt.userChoice
      if (outcome === 'accepted') {
        setInstalled(true)
      }
      deferredPrompt = null
      setInstallable(false)
    }
  }

  return { installable, installed, install }
}

export default function InstallPrompt() {
  const { installable, installed, install } = useInstallPrompt()
  const [dismissed, setDismissed] = useState(false)

  if (!installable || installed || dismissed) return null

  return (
    <div className="install-banner animate-fade-in">
      <div className="install-banner-content">
        <span className="install-icon">◈</span>
        <div className="install-text">
          <span className="install-title">Install UARTScope</span>
          <span className="install-subtitle">Add to home screen for the full app experience</span>
        </div>
      </div>
      <div className="install-actions">
        <button className="btn btn-primary btn-sm" onClick={install}>
          Install
        </button>
        <button className="btn btn-ghost btn-sm" onClick={() => setDismissed(true)}>
          Not now
        </button>
      </div>
    </div>
  )
}
