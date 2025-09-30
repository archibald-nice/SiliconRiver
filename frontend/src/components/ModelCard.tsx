import { ArrowTopRightOnSquareIcon } from "@heroicons/react/24/outline";

import type { ModelSummary } from "../api/client";

interface ModelCardProps {
  model: ModelSummary;
}

const ModelCard = ({ model }: ModelCardProps) => {
  return (
    <article className="group flex flex-col gap-3 rounded-xl border border-slate-800 bg-slate-900/40 p-4 transition hover:border-river-accent">
      <header className="flex items-start justify-between gap-2">
        <div>
          <p className="text-xs uppercase tracking-widest text-slate-400">{model.provider}</p>
          <h3 className="text-lg font-semibold text-river-accent">{model.model_name}</h3>
        </div>
        <a
          href={model.model_card_url}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 rounded-md border border-transparent bg-river-accent/10 px-2 py-1 text-xs text-river-accent transition group-hover:bg-river-accent/20"
        >
          详情
          <ArrowTopRightOnSquareIcon className="h-4 w-4" />
        </a>
      </header>
      <p className="text-sm text-slate-300">{model.description ?? "暂无描述"}</p>
      <footer className="flex flex-wrap items-center gap-3 text-xs text-slate-400">
        <span>发布时间：{new Date(model.created_at).toLocaleString()}</span>
        {typeof model.downloads === "number" && <span>下载量：{model.downloads.toLocaleString()}</span>}
        {typeof model.likes === "number" && <span>点赞：{model.likes.toLocaleString()}</span>}
      </footer>
      <div className="flex flex-wrap gap-2">
        {model.tags?.slice(0, 5).map((tag) => (
          <span key={tag} className="rounded-full bg-slate-800 px-2 py-1 text-xs text-slate-300">
            #{tag}
          </span>
        ))}
      </div>
    </article>
  );
};

export default ModelCard;
