import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react'

const ToastContext = createContext(null)

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([])
  const timers = useRef(new Map())

  const dismiss = useCallback((id) => {
    setToasts((rows) => rows.filter((row) => row.id !== id))
    const timer = timers.current.get(id)
    if (timer) clearTimeout(timer)
    timers.current.delete(id)
  }, [])

  const notify = useCallback((message, tone = 'default') => {
    const id = `${Date.now()}-${Math.random()}`
    setToasts((rows) => [...rows, { id, message, tone }])
    const timer = setTimeout(() => dismiss(id), 3400)
    timers.current.set(id, timer)
  }, [dismiss])

  const value = useMemo(() => ({ notify }), [notify])
  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toast-stack" aria-live="polite">
        {toasts.map((toast) => (
          <button key={toast.id} className={`toast ${toast.tone}`} onClick={() => dismiss(toast.id)}>
            {toast.message}
          </button>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast() {
  const ctx = useContext(ToastContext)
  return ctx || { notify: () => {} }
}
