import type { ModelSummary } from "../api/client";

interface TimelineRiverProps {
  models: ModelSummary[];
}

const TimelineRiver = ({ models }: TimelineRiverProps) => {
  return (
    <div className="relative">
      <div className="absolute left-4 top-0 h-full w-px bg-gradient-to-b from-river-accent/60 via-slate-700 to-transparent md:left-1/2" />
      <div className="space-y-8">
        {models.map((model, index) => {
          const isLeft = index % 2 === 0;
          return (
            <div key={model.model_id} className="relative flex flex-col md:flex-row md:items-center">
              <div
                className={`md:w-1/2 ${
                  isLeft ? "md:pr-12 md:text-right" : "md:pl-12 md:text-left md:ml-auto"
                }`}
              >
                <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4 shadow-lg shadow-river-accent/10">
                  <p className="text-xs uppercase tracking-widest text-slate-400">{model.provider}</p>
                  <h3 className="text-lg font-semibold text-white">{model.model_name}</h3>
                  <p className="mt-2 text-sm text-slate-300">{model.description ?? "暂无描述"}</p>
                  <p className="mt-3 text-xs text-slate-400">
                    {new Date(model.created_at).toLocaleString()} · 标签：{model.tags?.slice(0, 3).join("、")}
                  </p>
                </div>
              </div>
              <div className="relative my-4 flex h-10 w-full items-center justify-center md:my-0 md:w-0">
                <div className="flex h-8 w-8 items-center justify-center rounded-full border-2 border-river-accent bg-slate-950 text-xs text-river-accent">
                  {index + 1}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default TimelineRiver;
