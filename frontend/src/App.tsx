import { MoonIcon, SunIcon } from "@heroicons/react/24/outline";

import Home from "./pages/Home";
import { useTheme } from "./theme/ThemeProvider";

const App = () => {
  const { theme, toggleTheme } = useTheme();
  const isDark = theme === "dark";

  return (
    <div className="min-h-screen bg-surface-base text-text-primary transition-colors">
      <header className="border-b border-border-strong bg-surface-overlay backdrop-blur-md transition-colors">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-2 px-6 py-4">
          <div>
            <h1 className="text-xl font-semibold text-text-primary">硅基长河 · Silicon River</h1>
            <p className="text-sm text-text-muted">大模型发布一站式观察台</p>
          </div>
          <button
            type="button"
            aria-label="切换主题"
            onClick={toggleTheme}
            className="inline-flex items-center gap-2 rounded-full border border-border-default bg-surface-raised px-4 py-2 text-sm font-medium text-text-secondary shadow-sm transition-colors hover:border-accent-base hover:text-text-primary"
          >
            {isDark ? <SunIcon className="h-5 w-5" /> : <MoonIcon className="h-5 w-5" />}
            <span className="hidden sm:inline">{isDark ? "浅色模式" : "深色模式"}</span>
          </button>
        </div>
      </header>
      <main className="mx-auto px-6 py-8">
        <Home />
      </main>
    </div>
  );
};

export default App;
