import { MoonIcon, SunIcon } from "@heroicons/react/24/outline";

import Footer from "./components/Footer";
import Home from "./pages/Home";
import { useTheme } from "./theme/ThemeProvider";

const App = () => {
  const { theme, toggleTheme } = useTheme();
  const isDark = theme === "dark";

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-surface-base text-text-primary transition-colors">
      <header className="shrink-0 border-b border-border-strong bg-surface-overlay backdrop-blur-md transition-colors">
        <div className="flex w-full items-center justify-between gap-4 px-6 py-2">
          <div className="flex items-center gap-2">
            {/* 预留图标空间 */}
            <div className="h-6 w-6" />
            <div>
              <h1 className="text-lg font-semibold text-text-primary">硅基长河 · Silicon River</h1>
              <p className="text-xs text-text-muted">大模型发布一站式观察台</p>
            </div>
          </div>
          <button
            type="button"
            aria-label="切换主题"
            onClick={toggleTheme}
            className="shrink-0 inline-flex items-center gap-1.5 rounded-full border border-border-default bg-surface-raised px-3 py-1.5 text-xs font-medium text-text-secondary shadow-sm transition-colors hover:border-accent-base hover:text-text-primary"
          >
            {isDark ? <SunIcon className="h-4 w-4" /> : <MoonIcon className="h-4 w-4" />}
            <span className="hidden sm:inline">{isDark ? "浅色" : "深色"}</span>
          </button>
        </div>
      </header>
      <main className="flex min-w-0 flex-1 overflow-hidden px-6 py-3">
        <Home />
      </main>
      <Footer />
    </div>
  );
};

export default App;
