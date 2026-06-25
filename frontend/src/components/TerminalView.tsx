import { useRef, useEffect } from 'react';
import { Terminal } from 'lucide-react';

interface TerminalViewProps {
  messages: string[];
  fullHeight?: boolean;
}

export function TerminalView({ messages, fullHeight }: TerminalViewProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const autoScroll = useRef(true);

  useEffect(() => {
    if (autoScroll.current && containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [messages]);

  const handleScroll = () => {
    if (!containerRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = containerRef.current;
    autoScroll.current = scrollHeight - scrollTop - clientHeight < 50;
  };

  return (
    <div className={`flex h-full flex-col bg-slate-950 ${fullHeight ? 'rounded-lg' : ''}`}>
      <div className="flex items-center justify-between border-b border-slate-700 px-3 py-2">
        <div className="flex items-center gap-2">
          <Terminal className="h-4 w-4 text-emerald-400" />
          <span className="text-xs font-medium text-slate-300">Serial Terminal</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-slate-500">{messages.length} lines</span>
          <button
            onClick={() => { autoScroll.current = true; }}
            className="rounded bg-slate-700 px-2 py-0.5 text-[10px] text-slate-300 hover:bg-slate-600"
          >
            Auto-scroll
          </button>
        </div>
      </div>
      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-auto p-2 font-mono text-xs"
      >
        {messages.length === 0 ? (
          <div className="flex h-full items-center justify-center text-slate-600">
            <p>Waiting for data...</p>
          </div>
        ) : (
          messages.map((msg, i) => (
            <div key={i} className="py-0.5">
              <span className="text-slate-600 mr-2">[{new Date().toLocaleTimeString()}]</span>
              <span className="text-emerald-300">{msg}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
