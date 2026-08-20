import { useToastStore, type ToastType } from "../stores/toastStore";

const typeStyles: Record<ToastType, string> = {
  success: "bg-emerald-600/90 border-emerald-400/30 text-white",
  info: "bg-amber-600/90 border-amber-400/30 text-white",
  warning: "bg-amber-600/90 border-amber-400/30 text-white",
  error: "bg-red-600/90 border-red-400/30 text-white",
};

const icons: Record<ToastType, string> = {
  success: "✓",
  info: "ℹ",
  warning: "⚠",
  error: "✕",
};

export function ToastContainer() {
  const toasts = useToastStore((s) => s.toasts);
  const dismiss = useToastStore((s) => s.dismiss);

  return (
    <div className="fixed top-4 right-4 z-[9999] flex flex-col gap-2 pointer-events-none">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={`pointer-events-auto min-w-[220px] max-w-[360px] px-4 py-3 rounded-lg border shadow-lg backdrop-blur-sm flex items-start gap-3 animate-in slide-in-from-right fade-in ${typeStyles[t.type]}`}
        >
          <span className="font-bold">{icons[t.type]}</span>
          <span className="text-sm font-medium flex-1">{t.message}</span>
          <button
            onClick={() => dismiss(t.id)}
            className="opacity-70 hover:opacity-100 text-sm"
          >
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}
