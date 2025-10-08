import { ReactNode } from "react";

interface Tab {
  id: string;
  label: string;
  content: ReactNode;
}

interface TabSwitcherProps {
  tabs: Tab[];
  activeId: string;
  onTabChange: (id: string) => void;
  toolbar?: ReactNode;
}

const TabSwitcher = ({ tabs, activeId, onTabChange, toolbar }: TabSwitcherProps) => {
  const activeTab = tabs.find((tab) => tab.id === activeId);

  return (
    <section className="flex flex-col overflow-hidden rounded-2xl border border-border-default bg-surface-raised shadow-lg shadow-accent transition-colors">
      <div className="flex flex-col gap-4 border-b border-border-default px-6 py-4 lg:flex-row lg:items-center lg:justify-between">
        <nav className="flex flex-wrap items-center gap-2 text-text-secondary">
          {tabs.map((tab) => {
            const isActive = tab.id === activeId;
            const baseClasses = "rounded-full px-5 py-2 text-sm font-medium transition-colors";
            const activeClasses = isActive
              ? "bg-accent-base text-accent-contrast shadow-sm"
              : "bg-surface-chip text-text-secondary hover:text-text-primary";
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => onTabChange(tab.id)}
                className={`${baseClasses} ${activeClasses}`}
              >
                {tab.label}
              </button>
            );
          })}
        </nav>
        {toolbar ? (
          <div className="flex w-full flex-wrap gap-3 text-text-secondary lg:w-auto lg:justify-end">
            {toolbar}
          </div>
        ) : null}
      </div>
      <div className="p-6 transition-colors">{activeTab?.content}</div>
    </section>
  );
};

export default TabSwitcher;
