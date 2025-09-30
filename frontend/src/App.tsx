import Home from "./pages/Home";

const App = () => {
  return (
    <div className="min-h-screen bg-river-bg text-slate-100">
      <header className="border-b border-slate-800 bg-black/40 backdrop-blur-sm">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <h1 className="text-xl font-semibold">硅基长河 · Silicon River</h1>
          <span className="text-sm text-slate-400">大模型发布一站式观察台</span>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-6 py-8">
        <Home />
      </main>
    </div>
  );
};

export default App;
