import { ArrowTopRightOnSquareIcon } from "@heroicons/react/24/outline";

import type { ModelSummary } from "../api/client";

interface ModelCardProps {
  model: ModelSummary;
}

const ModelCard = ({ model }: ModelCardProps) => {
  return (
    <article className="group flex flex-col gap-3 rounded-xl border border-border-default bg-surface-raised p-4 transition-all hover:border-accent-base hover:shadow-accent">
      <header className="flex items-start justify-between gap-2">
        <div>
          <p className="text-xs uppercase tracking-widest text-text-muted">{model.provider}</p>
          <h3 className="text-lg font-semibold text-accent-base">{model.model_name}</h3>
        </div>
        <a
          href={model.model_card_url}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 rounded-md border border-transparent bg-accent-soft px-2 py-1 text-xs text-accent-base transition group-hover:border-accent-base"
        >
          详情
          <ArrowTopRightOnSquareIcon className="h-4 w-4" />
        </a>
      </header>
      <p className="text-sm text-text-secondary">{model.description ?? "暂无描述"}</p>
      <footer className="flex flex-wrap items-center gap-3 text-xs text-text-muted">
        <span>发布时间：{new Date(model.created_at).toLocaleString()}</span>
        {typeof model.downloads === "number" && <span>下载量：{model.downloads.toLocaleString()}</span>}
        {typeof model.likes === "number" && <span>点赞：{model.likes.toLocaleString()}</span>}
      </footer>
      <div className="flex flex-wrap gap-2">
        {model.tags?.slice(0, 5).map((tag) => (
          <span key={tag} className="rounded-full bg-surface-chip px-2 py-1 text-xs text-text-secondary">
            #{tag}
          </span>
        ))}
      </div>
    </article>
  );
};

export default ModelCard;
