const Footer = () => {
  const tags = [
    "本网站获取信息来源：HuggingFace、OpenRouter",
    "开源模型拉取频率：每 1 小时",
    "闭源模型拉取频率：每 6 小时",
  ];

  return (
    <footer className="shrink-0 border-t border-border-default bg-surface-overlay py-3 transition-colors">
      <div className="flex flex-wrap items-center justify-center gap-3">
        {tags.map((tag, index) => (
          <div
            key={index}
            className="inline-flex items-center rounded-full border border-accent-base/10 bg-accent-soft px-3 py-1.5 text-xs font-medium text-accent-base"
          >
            {tag}
          </div>
        ))}
      </div>
    </footer>
  );
};

export default Footer;
